from datetime import datetime, timedelta

from job_portal.models import Session as SessionModel
from job_portal.services.auth import (
    create_session,
    delete_session,
    get_session,
    hash_password,
    verify_password,
)


def test_hash_password_does_not_return_plaintext():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert len(hashed) > 20


def test_verify_password_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_create_and_get_session(db_session):
    token = create_session(db_session, "seeker", 42)
    session = get_session(db_session, token)
    assert session is not None
    assert session.account_type == "seeker"
    assert session.account_id == 42


def test_get_session_returns_none_for_unknown_token(db_session):
    assert get_session(db_session, "not-a-real-token") is None


def test_get_session_returns_none_for_expired_session(db_session):
    token = create_session(db_session, "seeker", 42)
    session = db_session.query(SessionModel).filter(SessionModel.token == token).first()
    session.expires_at = datetime.utcnow() - timedelta(days=1)
    db_session.commit()
    assert get_session(db_session, token) is None


def test_delete_session_invalidates_it(db_session):
    token = create_session(db_session, "seeker", 42)
    delete_session(db_session, token)
    assert get_session(db_session, token) is None


def test_delete_sessions_for_account_only_removes_target_account(db_session):
    from job_portal.services.auth import create_session, delete_sessions_for_account, get_session

    token_a1 = create_session(db_session, "seeker", 1)
    token_a2 = create_session(db_session, "seeker", 1)
    token_b = create_session(db_session, "seeker", 2)
    token_employer = create_session(db_session, "employer", 1)

    delete_sessions_for_account(db_session, "seeker", 1)

    assert get_session(db_session, token_a1) is None
    assert get_session(db_session, token_a2) is None
    assert get_session(db_session, token_b) is not None
    assert get_session(db_session, token_employer) is not None


