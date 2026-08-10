"""
Account registration, login, logout, and session lookup (US-01, US-02,
US-04, US-06). See docs/superpowers/specs/2026-08-01-identity-auth-foundation-design.md
for the full design — this is sub-project 1 of 4 in the account/auth epic;
nothing here changes any *existing* endpoint's identity handling yet.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from job_portal.database import get_db
from job_portal.models import Admin, Employer, SeekerProfile
from job_portal.schemas import AuthAccountOut, EmployerRegisterIn, LoginIn, SeekerRegisterIn
from job_portal.services.auth import (
    create_session,
    delete_session,
    get_session,
    hash_password,
    verify_password,
    verify_password_or_dummy,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE_NAME = "session_token"


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

    profile = SeekerProfile(
        seeker_id=next_seeker_id,
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        status="active",
        skills="",
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    token = create_session(db, "seeker", profile.seeker_id)
    _set_session_cookie(response, token)

    return AuthAccountOut(
        role="seeker", id=profile.seeker_id, email=profile.email, display_name=profile.full_name
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
    )
    db.add(employer)
    db.commit()
    db.refresh(employer)

    token = create_session(db, "employer", employer.id)
    _set_session_cookie(response, token)

    return AuthAccountOut(
        role="employer", id=employer.id, email=employer.email, display_name=employer.company_name
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
            role="seeker", id=seeker.seeker_id, email=seeker.email, display_name=seeker.full_name or ""
        )

    employer = db.query(Employer).filter(Employer.email == email).first()
    if employer is not None:
        if not verify_password_or_dummy(payload.password, employer.hashed_password):
            raise HTTPException(status_code=401, detail="Incorrect email or password.")
        if employer.status == "suspended":
            raise HTTPException(status_code=403, detail="This account has been suspended.")
        token = create_session(db, "employer", employer.id)
        _set_session_cookie(response, token)
        return AuthAccountOut(
            role="employer", id=employer.id, email=employer.email, display_name=employer.company_name
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
            role="seeker", id=seeker.seeker_id, email=seeker.email, display_name=seeker.full_name or ""
        )
    if role == "employer":
        employer = db.query(Employer).filter(Employer.id == account_id).first()
        if employer is None:
            raise HTTPException(status_code=401, detail="Account no longer exists.")
        return AuthAccountOut(
            role="employer", id=employer.id, email=employer.email, display_name=employer.company_name
        )
    admin = db.query(Admin).filter(Admin.id == account_id).first()
    if admin is None:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return AuthAccountOut(role="admin", id=admin.id, email=admin.email, display_name="Admin")
