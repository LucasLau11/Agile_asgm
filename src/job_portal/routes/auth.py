"""
Account registration, login, logout, and session lookup (US-01, US-02,
US-04, US-06), plus email confirmation (US-68), password reset
(US-69/US-73), change password (US-70/US-74), and self-service account
deletion (US-71). See docs/superpowers/specs/2026-08-01-identity-auth-foundation-design.md
for the original auth foundation design — this file has since grown
beyond that sub-project's original scope to cover the rest of the
account-management epic.
"""

import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from job_portal.database import get_db
from job_portal.models import Admin, Employer, SeekerProfile
from job_portal.schemas import (
    AuthAccountOut,
    ChangePasswordIn,
    ConfirmEmailIn,
    DeleteAccountIn,
    EmployerRegisterIn,
    ForgotPasswordIn,
    LoginIn,
    ResetPasswordIn,
    SeekerRegisterIn,
)
from job_portal.services.account_deletion import delete_employer_account, delete_seeker_account
from job_portal.services.auth import (
    create_session,
    delete_session,
    delete_sessions_for_account,
    get_session,
    hash_password,
    verify_password,
    verify_password_or_dummy,
)
from job_portal.services.email import (
    EmailNotConfigured,
    send_confirmation_email,
    send_password_reset_email,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE_NAME = "session_token"

# How long a confirmation/reset link stays valid before the recipient has
# to request a fresh one.
CONFIRMATION_TOKEN_LIFETIME = timedelta(hours=24)
RESET_TOKEN_LIFETIME = timedelta(hours=1)

# Base URL used to build links inside emails. In a real deployment this
# would come from an environment variable (the deployed domain); hardcoded
# to the local dev server here since that's the only place this app runs.
APP_BASE_URL = "http://127.0.0.1:8000"


def _email_taken(db: DBSession, email: str) -> bool:
    """Cross-table uniqueness check: one email can only ever belong to one
    account, in one role, so POST /api/auth/login can look an email up
    unambiguously without asking which role it belongs to. Note this also
    catches emails belonging to pre-existing seeded profiles that have no
    password (hashed_password IS NULL) — those can't log in, but they still
    "own" that email address, so a new registration under it is rejected
    rather than silently taking it over."""
    return (
        db.query(SeekerProfile).filter(func.lower(SeekerProfile.email) == email).first() is not None
        or db.query(Employer).filter(Employer.email == email).first() is not None
        or db.query(Admin).filter(Admin.email == email).first() is not None
    )


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # local dev runs over plain HTTP; set True before any HTTPS deployment
        max_age=7 * 24 * 60 * 60,
    )


def _try_send(send_fn, *args) -> None:
    """Best-effort email send: registration/reset should still succeed
    even if Mailtrap is unreachable or MAILTRAP_API_TOKEN isn't configured
    on this machine — the alternative (500ing the whole request) would
    make the app unusable for anyone who hasn't set up a .env yet. The
    token/reset row is still saved either way, so a resend or a manually
    shared link still works."""
    try:
        send_fn(*args)
    except (EmailNotConfigured, Exception):
        pass


@router.post("/register/seeker", response_model=AuthAccountOut, status_code=201)
def register_seeker(
    payload: SeekerRegisterIn, response: Response, db: DBSession = Depends(get_db)
) -> AuthAccountOut:
    if _email_taken(db, payload.email):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    # seeker_id is a separate, required-unique column from the autoincrement
    # `id` PK (pre-existing design, see models.py) — pick the next free value
    # rather than trying to know `id` before the row is inserted.
    next_seeker_id = (db.query(func.max(SeekerProfile.seeker_id)).scalar() or 0) + 1

    confirmation_token = secrets.token_urlsafe(32)
    profile = SeekerProfile(
        seeker_id=next_seeker_id,
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        status="active",
        skills="",
        email_confirmed=0,
        confirmation_token=confirmation_token,
        confirmation_token_expires=datetime.utcnow() + CONFIRMATION_TOKEN_LIFETIME,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    confirm_url = f"{APP_BASE_URL}/UI/html/confirm_email.html?token={confirmation_token}"
    _try_send(send_confirmation_email, profile.email, confirm_url)

    token = create_session(db, "seeker", profile.seeker_id)
    _set_session_cookie(response, token)

    return AuthAccountOut(
        role="seeker",
        id=profile.seeker_id,
        email=profile.email,
        display_name=profile.full_name,
        email_confirmed=False,
    )


@router.post("/register/employer", response_model=AuthAccountOut, status_code=201)
def register_employer(
    payload: EmployerRegisterIn, response: Response, db: DBSession = Depends(get_db)
) -> AuthAccountOut:
    if _email_taken(db, payload.email):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    employer = Employer(
        company_name=payload.company_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        status="active",
        verification_status="pending",
    )
    db.add(employer)
    db.commit()
    db.refresh(employer)

    token = create_session(db, "employer", employer.id)
    _set_session_cookie(response, token)

    return AuthAccountOut(
        role="employer",
        id=employer.id,
        email=employer.email,
        display_name=employer.company_name,
        email_confirmed=True,
    )


@router.post("/login", response_model=AuthAccountOut)
def login(payload: LoginIn, response: Response, db: DBSession = Depends(get_db)) -> AuthAccountOut:
    email = payload.email.strip().lower()

    seeker = (
        db.query(SeekerProfile)
        .filter(func.lower(SeekerProfile.email) == email, SeekerProfile.hashed_password.isnot(None))
        .first()
    )
    if seeker is not None:
        if not verify_password_or_dummy(payload.password, seeker.hashed_password):
            raise HTTPException(status_code=401, detail="Incorrect email or password.")
        if seeker.status == "suspended":
            raise HTTPException(status_code=403, detail="This account has been suspended.")
        token = create_session(db, "seeker", seeker.seeker_id)
        _set_session_cookie(response, token)
        return AuthAccountOut(
            role="seeker",
            id=seeker.seeker_id,
            email=seeker.email,
            display_name=seeker.full_name or "",
            email_confirmed=bool(seeker.email_confirmed),
        )

    employer = db.query(Employer).filter(Employer.email == email).first()
    if employer is not None:
        if not verify_password_or_dummy(payload.password, employer.hashed_password):
            raise HTTPException(status_code=401, detail="Incorrect email or password.")
        if employer.status == "suspended":
            raise HTTPException(status_code=403, detail="This account has been suspended.")
        if employer.verification_status == "rejected":
            raise HTTPException(status_code=403, detail="This employer registration was rejected.")
        token = create_session(db, "employer", employer.id)
        _set_session_cookie(response, token)
        return AuthAccountOut(
            role="employer",
            id=employer.id,
            email=employer.email,
            display_name=employer.company_name,
            email_confirmed=True,
        )

    admin = db.query(Admin).filter(Admin.email == email).first()
    if admin is not None:
        if not verify_password_or_dummy(payload.password, admin.hashed_password):
            raise HTTPException(status_code=401, detail="Incorrect email or password.")
        token = create_session(db, "admin", admin.id)
        _set_session_cookie(response, token)
        return AuthAccountOut(role="admin", id=admin.id, email=admin.email, display_name="Admin")

    # Nothing matched in any table — still do dummy verification work so
    # this path takes about as long as a real "wrong password" check.
    verify_password_or_dummy(payload.password, None)
    raise HTTPException(status_code=401, detail="Incorrect email or password.")


@router.post("/logout")
def logout(
    response: Response,
    session_token: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
    db: DBSession = Depends(get_db),
) -> dict:
    if session_token:
        delete_session(db, session_token)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"success": True}


def get_current_account(
    session_token: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
    db: DBSession = Depends(get_db),
) -> dict:
    """Shared dependency: resolves the session cookie to {role, id}.
    Reused by /me here, and intended for a later sub-project to reuse
    across every existing endpoint once that retrofit happens."""
    if not session_token:
        raise HTTPException(status_code=401, detail="Not logged in.")
    session = get_session(db, session_token)
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    return {"role": session.account_type, "id": session.account_id}


def require_role(role: str, message: Optional[str] = None):
    """Dependency factory: Depends(require_role("seeker")) raises 401 if the
    session isn't logged in as that role, otherwise resolves directly to the
    account's id — skipping the `account["role"] != role` boilerplate every
    call site used to repeat. Replaces the one-off _require_seeker helper
    that used to live in routes/seeker.py, and the inline role check in
    applications.py's fragment endpoint."""
    detail = message or f"Must be logged in as a {role}."

    def _dependency(account: dict = Depends(get_current_account)) -> int:
        if account["role"] != role:
            raise HTTPException(status_code=401, detail=detail)
        return account["id"]

    return _dependency


def require_participant_role(message: Optional[str] = None):
    """Dependency factory for endpoints usable by EITHER a seeker or an
    employer (but not admin) — returns the full account dict {role, id},
    unlike require_role which only returns an id for one fixed role.
    Messaging is the first surface in this app where the actor's role
    genuinely varies per request rather than being fixed by the route."""
    detail = message or "Must be logged in as a seeker or employer."

    def _dependency(account: dict = Depends(get_current_account)) -> dict:
        if account["role"] not in ("seeker", "employer"):
            raise HTTPException(status_code=401, detail=detail)
        return account

    return _dependency


def get_current_account_optional(
    session_token: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
    db: DBSession = Depends(get_db),
) -> Optional[dict]:
    """Like get_current_account, but resolves to None instead of raising
    when there's no valid session — for endpoints where personalization is
    a bonus, not a requirement (e.g. public job browsing)."""
    if not session_token:
        return None
    session = get_session(db, session_token)
    if session is None:
        return None
    return {"role": session.account_type, "id": session.account_id}


@router.get("/me", response_model=AuthAccountOut)
def get_me(account: dict = Depends(get_current_account), db: DBSession = Depends(get_db)) -> AuthAccountOut:
    role, account_id = account["role"], account["id"]
    if role == "seeker":
        seeker = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == account_id).first()
        if seeker is None:
            raise HTTPException(status_code=401, detail="Account no longer exists.")
        return AuthAccountOut(
            role="seeker",
            id=seeker.seeker_id,
            email=seeker.email,
            display_name=seeker.full_name or "",
            email_confirmed=bool(seeker.email_confirmed),
        )
    if role == "employer":
        employer = db.query(Employer).filter(Employer.id == account_id).first()
        if employer is None:
            raise HTTPException(status_code=401, detail="Account no longer exists.")
        return AuthAccountOut(
            role="employer",
            id=employer.id,
            email=employer.email,
            display_name=employer.company_name,
            email_confirmed=True,
        )
    admin = db.query(Admin).filter(Admin.id == account_id).first()
    if admin is None:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return AuthAccountOut(role="admin", id=admin.id, email=admin.email, display_name="Admin")


# ---------------------------------------------------------------------------
# US-68: email confirmation
# ---------------------------------------------------------------------------


@router.post("/confirm-email", response_model=AuthAccountOut)
def confirm_email(payload: ConfirmEmailIn, db: DBSession = Depends(get_db)) -> AuthAccountOut:
    seeker = (
        db.query(SeekerProfile)
        .filter(SeekerProfile.confirmation_token == payload.token)
        .first()
    )
    if seeker is None:
        raise HTTPException(status_code=400, detail="This confirmation link is invalid.")
    if seeker.confirmation_token_expires and seeker.confirmation_token_expires < datetime.utcnow():
        raise HTTPException(
            status_code=400,
            detail="This confirmation link has expired. Please request a new one.",
        )

    seeker.email_confirmed = 1
    seeker.confirmation_token = None
    seeker.confirmation_token_expires = None
    db.commit()
    db.refresh(seeker)

    return AuthAccountOut(
        role="seeker",
        id=seeker.seeker_id,
        email=seeker.email,
        display_name=seeker.full_name or "",
        email_confirmed=True,
    )


@router.post("/resend-confirmation")
def resend_confirmation(
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: DBSession = Depends(get_db),
) -> dict:
    seeker = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == seeker_id).first()
    if seeker is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    if seeker.email_confirmed:
        return {"success": True, "message": "Your email is already confirmed."}

    confirmation_token = secrets.token_urlsafe(32)
    seeker.confirmation_token = confirmation_token
    seeker.confirmation_token_expires = datetime.utcnow() + CONFIRMATION_TOKEN_LIFETIME
    db.commit()

    confirm_url = f"{APP_BASE_URL}/UI/html/confirm_email.html?token={confirmation_token}"
    _try_send(send_confirmation_email, seeker.email, confirm_url)

    return {"success": True, "message": "Confirmation email sent."}


# ---------------------------------------------------------------------------
# US-69/US-73: forgot password (unauthenticated — request + reset by token)
# ---------------------------------------------------------------------------


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordIn, db: DBSession = Depends(get_db)) -> dict:
    """Always returns the same generic message whether or not the email
    exists — this is deliberate. A different response for "no such
    account" vs "reset email sent" would let anyone probe which emails are
    registered on the platform."""
    email = payload.email.strip().lower()
    generic_response = {
        "success": True,
        "message": "If an account exists with that email, a password reset link has been sent.",
    }

    seeker = (
        db.query(SeekerProfile)
        .filter(func.lower(SeekerProfile.email) == email, SeekerProfile.hashed_password.isnot(None))
        .first()
    )
    if seeker is not None:
        reset_token = secrets.token_urlsafe(32)
        seeker.reset_token = reset_token
        seeker.reset_token_expires = datetime.utcnow() + RESET_TOKEN_LIFETIME
        db.commit()
        reset_url = f"{APP_BASE_URL}/UI/html/reset_password.html?token={reset_token}&role=seeker"
        _try_send(send_password_reset_email, seeker.email, reset_url)
        return generic_response

    employer = db.query(Employer).filter(Employer.email == email).first()
    if employer is not None:
        reset_token = secrets.token_urlsafe(32)
        employer.reset_token = reset_token
        employer.reset_token_expires = datetime.utcnow() + RESET_TOKEN_LIFETIME
        db.commit()
        reset_url = f"{APP_BASE_URL}/UI/html/reset_password.html?token={reset_token}&role=employer"
        _try_send(send_password_reset_email, employer.email, reset_url)
        return generic_response

    return generic_response


@router.post("/reset-password")
def reset_password(payload: ResetPasswordIn, db: DBSession = Depends(get_db)) -> dict:
    seeker = db.query(SeekerProfile).filter(SeekerProfile.reset_token == payload.token).first()
    if seeker is not None:
        if seeker.reset_token_expires and seeker.reset_token_expires < datetime.utcnow():
            raise HTTPException(status_code=400, detail="This reset link has expired. Please request a new one.")
        seeker.hashed_password = hash_password(payload.new_password)
        seeker.reset_token = None
        seeker.reset_token_expires = None
        db.commit()
        # Invalidate any existing sessions — if someone else's session was
        # active on this account, a password reset should end it, the same
        # way it would on any real platform.
        delete_sessions_for_account(db, "seeker", seeker.seeker_id)
        return {"success": True, "message": "Password reset. You can now log in with your new password."}

    employer = db.query(Employer).filter(Employer.reset_token == payload.token).first()
    if employer is not None:
        if employer.reset_token_expires and employer.reset_token_expires < datetime.utcnow():
            raise HTTPException(status_code=400, detail="This reset link has expired. Please request a new one.")
        employer.hashed_password = hash_password(payload.new_password)
        employer.reset_token = None
        employer.reset_token_expires = None
        db.commit()
        delete_sessions_for_account(db, "employer", employer.id)
        return {"success": True, "message": "Password reset. You can now log in with your new password."}

    raise HTTPException(status_code=400, detail="This reset link is invalid or has already been used.")


# ---------------------------------------------------------------------------
# US-70/US-74: change password (logged in)
# ---------------------------------------------------------------------------


@router.post("/change-password")
def change_password(
    payload: ChangePasswordIn,
    account: dict = Depends(require_participant_role("Must be logged in.")),
    db: DBSession = Depends(get_db),
) -> dict:
    role, account_id = account["role"], account["id"]

    if role == "seeker":
        seeker = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == account_id).first()
        if seeker is None:
            raise HTTPException(status_code=404, detail="Account not found.")
        if not verify_password(payload.current_password, seeker.hashed_password or ""):
            raise HTTPException(status_code=401, detail="Current password is incorrect.")
        seeker.hashed_password = hash_password(payload.new_password)
        db.commit()
        return {"success": True, "message": "Password changed."}

    employer = db.query(Employer).filter(Employer.id == account_id).first()
    if employer is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    if not verify_password(payload.current_password, employer.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    employer.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"success": True, "message": "Password changed."}


# ---------------------------------------------------------------------------
# US-71: delete own account (seeker self-service)
# ---------------------------------------------------------------------------


@router.delete("/me", status_code=204)
def delete_my_account(
    payload: DeleteAccountIn,
    response: Response,
    account: dict = Depends(require_participant_role("Must be logged in.")),
    db: DBSession = Depends(get_db),
) -> None:
    """Delete own account (both seeker and employer).
    US-71 for seeker, similar for employer.
    Password-confirmed, so a session left open on a shared computer can't
    be used to destroy the account outright. Reuses the same cascade as
    admin-initiated deletion (services/account_deletion.py)."""
    role, account_id = account["role"], account["id"]

    if role == "seeker":
        seeker = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == account_id).first()
        if seeker is None:
            raise HTTPException(status_code=404, detail="Account not found.")
        if not verify_password(payload.password, seeker.hashed_password or ""):
            raise HTTPException(status_code=401, detail="Password is incorrect.")
        delete_seeker_account(db, seeker)

    elif role == "employer":
        employer = db.query(Employer).filter(Employer.id == account_id).first()
        if employer is None:
            raise HTTPException(status_code=404, detail="Account not found.")
        if not verify_password(payload.password, employer.hashed_password):
            raise HTTPException(status_code=401, detail="Password is incorrect.")
        delete_employer_account(db, employer)

    response.delete_cookie(SESSION_COOKIE_NAME)