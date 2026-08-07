"""
Password hashing and session-token helpers for the account/auth foundation
(US-01, US-02, US-04, US-06).

Sessions are plain database rows, not signed/stateless tokens (JWTs) — the
token is a cryptographically random opaque string, looked up in the
`sessions` table on every authenticated request. That makes logout a
straightforward row delete: real revocation, no blocklist needed.
"""

import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from sqlalchemy.orm import Session as DBSession

from job_portal.models import Session as SessionModel

SESSION_LIFETIME = timedelta(days=7)


def hash_password(plain: str) -> str:
    """bcrypt embeds its own random salt in the output, so no separate
    salt column is needed anywhere this hash gets stored."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        # Not a valid bcrypt hash (shouldn't happen for rows created via
        # hash_password, but fails closed rather than raising if it does).
        return False


# A fixed hash to check against when no real account was found, so a
# login attempt against a nonexistent email takes roughly the same time
# as one against a real account with a wrong password — closes a timing
# side-channel that would otherwise let an attacker distinguish "no such
# email" from "wrong password" by response latency alone, even though
# the response body/status are already identical for both cases.
_DUMMY_HASH = hash_password("not-a-real-password-just-for-timing")


def verify_password_or_dummy(plain: str, hashed: Optional[str]) -> bool:
    """Like verify_password, but always does bcrypt-equivalent work even
    when there's no real hash to check against (hashed is None/empty) —
    call this instead of verify_password on any code path where "no
    account found" and "account found, wrong password" must be
    indistinguishable by timing."""
    if not hashed:
        verify_password(plain, _DUMMY_HASH)  # burn the same time, discard the result
        return False
    return verify_password(plain, hashed)


def create_session(db: DBSession, account_type: str, account_id: int) -> str:
    token = secrets.token_urlsafe(32)
    session = SessionModel(
        token=token,
        account_type=account_type,
        account_id=account_id,
        expires_at=datetime.utcnow() + SESSION_LIFETIME,
    )
    db.add(session)
    db.commit()
    return token


def get_session(db: DBSession, token: str) -> Optional[SessionModel]:
    session = db.query(SessionModel).filter(SessionModel.token == token).first()
    if session is None:
        return None
    if session.expires_at < datetime.utcnow():
        return None
    return session


def delete_session(db: DBSession, token: str) -> None:
    db.query(SessionModel).filter(SessionModel.token == token).delete()
    db.commit()
