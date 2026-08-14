def test_register_seeker_success(client):
    res = client.post("/api/auth/register/seeker", json={
        "full_name": "Test Seeker",
        "email": "test.seeker@gmail.com",
        "password": "correcthorse",
    })
    assert res.status_code == 201
    body = res.json()
    assert body["role"] == "seeker"
    assert body["email"] == "test.seeker@gmail.com"
    assert body["display_name"] == "Test Seeker"
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_seeker_duplicate_email_rejected(client):
    payload = {"full_name": "Test Seeker", "email": "dupe@gmail.com", "password": "correcthorse"}
    first = client.post("/api/auth/register/seeker", json=payload)
    assert first.status_code == 201
    second = client.post("/api/auth/register/seeker", json=payload)
    assert second.status_code == 409


def test_register_employer_duplicate_email_rejected_cross_role(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Test Seeker", "email": "shared@gmail.com", "password": "correcthorse",
    })
    res = client.post("/api/auth/register/employer", json={
        "company_name": "Test Co", "email": "shared@gmail.com", "password": "correcthorse",
    })
    assert res.status_code == 409


def test_register_seeker_password_too_short(client):
    res = client.post("/api/auth/register/seeker", json={
        "full_name": "Test Seeker", "email": "short@gmail.com", "password": "short",
    })
    assert res.status_code == 422


def test_register_seeker_invalid_name_rejected(client):
    res = client.post("/api/auth/register/seeker", json={
        "full_name": "Test123", "email": "badname@gmail.com", "password": "correcthorse",
    })
    assert res.status_code == 422


def test_register_employer_success(client):
    res = client.post("/api/auth/register/employer", json={
        "company_name": "Test Co",
        "email": "hr@gmail.com",
        "password": "correcthorse",
    })
    assert res.status_code == 201
    body = res.json()
    assert body["role"] == "employer"
    assert body["display_name"] == "Test Co"
    assert "hashed_password" not in body


def test_register_employer_blank_company_name_rejected(client):
    res = client.post("/api/auth/register/employer", json={
        "company_name": "   ",
        "email": "blank@gmail.com",
        "password": "correcthorse",
    })
    assert res.status_code == 422


def test_register_seeker_allowed_domain_accepted(client):
    res = client.post("/api/auth/register/seeker", json={
        "full_name": "Domain Ok", "email": "domain.ok@yahoo.com", "password": "correcthorse",
    })
    assert res.status_code == 201


def test_register_seeker_academic_domain_accepted(client):
    res = client.post("/api/auth/register/seeker", json={
        "full_name": "Domain Academic", "email": "domain.student@tarc.edu.my", "password": "correcthorse",
    })
    assert res.status_code == 201


def test_register_employer_allowed_domain_accepted(client):
    res = client.post("/api/auth/register/employer", json={
        "company_name": "Domain Ok Co", "email": "domain.ok.employer@outlook.com", "password": "correcthorse",
    })
    assert res.status_code == 201


def test_register_employer_academic_domain_accepted(client):
    res = client.post("/api/auth/register/employer", json={
        "company_name": "Domain Academic Co", "email": "domain.hr@university.edu", "password": "correcthorse",
    })
    assert res.status_code == 201


def test_login_success(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Login Test", "email": "login.test@gmail.com", "password": "correcthorse",
    })
    client.post("/api/auth/logout")  # clear the auto-login session from registration
    res = client.post("/api/auth/login", json={"email": "login.test@gmail.com", "password": "correcthorse"})
    assert res.status_code == 200
    assert res.json()["email"] == "login.test@gmail.com"


def test_login_wrong_password_generic_401(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Wrong Pw", "email": "wrongpw@gmail.com", "password": "correcthorse",
    })
    res = client.post("/api/auth/login", json={"email": "wrongpw@gmail.com", "password": "incorrect"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect email or password."


def test_login_unknown_email_same_generic_401(client):
    res = client.post("/api/auth/login", json={"email": "nobody@gmail.com", "password": "whatever"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect email or password."


def test_admin_can_log_in(client, db_session):
    from job_portal.models import Admin
    from job_portal.services.auth import hash_password

    admin = Admin(email="admin.test@gmail.com", hashed_password=hash_password("correcthorse"))
    db_session.add(admin)
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "admin.test@gmail.com", "password": "correcthorse"})
    assert res.status_code == 200
    assert res.json()["role"] == "admin"


def test_login_rejects_suspended_seeker(client, db_session):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Suspended", "email": "suspended@gmail.com", "password": "correcthorse",
    })
    client.post("/api/auth/logout")

    from job_portal.models import SeekerProfile
    profile = db_session.query(SeekerProfile).filter(SeekerProfile.email == "suspended@gmail.com").first()
    profile.status = "suspended"
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "suspended@gmail.com", "password": "correcthorse"})
    assert res.status_code == 403


def test_login_wrong_password_on_suspended_account_still_generic_401(client, db_session):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Suspended Wrong Pw", "email": "suspended.wrongpw@gmail.com", "password": "correcthorse",
    })
    client.post("/api/auth/logout")

    from job_portal.models import SeekerProfile
    profile = db_session.query(SeekerProfile).filter(SeekerProfile.email == "suspended.wrongpw@gmail.com").first()
    profile.status = "suspended"
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "suspended.wrongpw@gmail.com", "password": "totally-wrong"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect email or password."


def test_me_requires_session(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_logout_invalidates_session(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Logout Test", "email": "logout.test@gmail.com", "password": "correcthorse",
    })
    client.post("/api/auth/logout")
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_register_then_me_reflects_logged_in_account(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Me Test", "email": "me.test@gmail.com", "password": "correcthorse",
    })
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "seeker"
    assert body["email"] == "me.test@gmail.com"
    assert "hashed_password" not in body


def test_employer_login_success(client):
    client.post("/api/auth/register/employer", json={
        "company_name": "Login Test Co", "email": "employer.login@gmail.com", "password": "correcthorse",
    })
    client.post("/api/auth/logout")
    res = client.post("/api/auth/login", json={"email": "employer.login@gmail.com", "password": "correcthorse"})
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "employer"
    assert body["email"] == "employer.login@gmail.com"


def test_employer_login_rejects_suspended(client, db_session):
    client.post("/api/auth/register/employer", json={
        "company_name": "Suspended Co", "email": "employer.suspended@gmail.com", "password": "correcthorse",
    })
    client.post("/api/auth/logout")

    from job_portal.models import Employer
    employer = db_session.query(Employer).filter(Employer.email == "employer.suspended@gmail.com").first()
    employer.status = "suspended"
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "employer.suspended@gmail.com", "password": "correcthorse"})
    assert res.status_code == 403


def test_register_employer_then_me_reflects_logged_in_account(client):
    client.post("/api/auth/register/employer", json={
        "company_name": "Me Test Co", "email": "employer.me@gmail.com", "password": "correcthorse",
    })
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "employer"
    assert body["email"] == "employer.me@gmail.com"
    assert body["display_name"] == "Me Test Co"
    assert "hashed_password" not in body


def test_login_not_blocked_by_passwordless_profile_sharing_email(client, db_session):
    # Simulates a legacy/pre-auth seeded profile with no password, sharing
    # an email with a real registered account (both rows inserted directly,
    # bypassing the register endpoint, since Finding 2's case-insensitive
    # uniqueness check would otherwise reject registering over an email a
    # legacy row already "owns"). Login must find and authenticate the
    # credentialed row, not silently fail because .first() picked the
    # passwordless one.
    from job_portal.models import SeekerProfile
    from job_portal.services.auth import hash_password

    legacy = SeekerProfile(seeker_id=9001, full_name="Legacy", email="shared.email@gmail.com", skills="")
    db_session.add(legacy)
    real = SeekerProfile(
        seeker_id=9002, full_name="Real Account", email="shared.email@gmail.com",
        hashed_password=hash_password("correcthorse"), status="active", skills="",
    )
    db_session.add(real)
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "shared.email@gmail.com", "password": "correcthorse"})
    assert res.status_code == 200
    assert res.json()["display_name"] == "Real Account"


def test_seeded_style_account_can_log_in(client, db_session):
    """Confirms the pattern seed.py uses (hash_password + status="active"
    on a SeekerProfile) actually produces a row that can log in — not a
    subprocess invocation of seed.py itself (which targets the real dev
    database, not the test one), just the same row-creation logic exercised
    against the test DB the way every other fixture in this suite is."""
    from job_portal.models import SeekerProfile
    from job_portal.services.auth import hash_password

    seeded = SeekerProfile(
        seeker_id=1,
        full_name="Aisha Rahman",
        email="aisha.rahman@gmail.com",
        phone="012-345 6789",
        bio="Backend-leaning full-stack developer.",
        skills="Python,FastAPI,SQL,Docker",
        hashed_password=hash_password("password123"),
        status="active",
    )
    db_session.add(seeded)
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "aisha.rahman@gmail.com", "password": "password123"})
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "seeker"
    assert body["display_name"] == "Aisha Rahman"


from fastapi import HTTPException
import pytest

from job_portal.routes.auth import get_current_account_optional, require_role
from job_portal.services.auth import create_session


def test_get_current_account_optional_no_session_returns_none(db_session):
    result = get_current_account_optional(session_token=None, db=db_session)
    assert result is None


def test_get_current_account_optional_invalid_session_returns_none(db_session):
    result = get_current_account_optional(session_token="not-a-real-token", db=db_session)
    assert result is None


def test_get_current_account_optional_valid_session_returns_account(db_session):
    token = create_session(db_session, "seeker", 7)
    result = get_current_account_optional(session_token=token, db=db_session)
    assert result == {"role": "seeker", "id": 7}


def test_get_company_detail_returns_verified_public_profile(client, db_session):
    from job_portal.models import Employer

    employer = Employer(
        company_name="Northwind Labs",
        email="northwind@gmail.com",
        hashed_password="ignored",
        description="We build AI services.",
        industry="Technology",
        website="https://northwind.example",
        verification_status="approved",
    )
    db_session.add(employer)
    db_session.commit()
    db_session.refresh(employer)

    res = client.get(f"/api/companies/{employer.id}")
    assert res.status_code == 200
    assert res.json() == {
        "id": employer.id,
        "company_name": "Northwind Labs",
        "description": "We build AI services.",
        "industry": "Technology",
        "website": "https://northwind.example",
        "is_verified": True,
    }


def test_seeker_can_upload_profile_picture(client):
    client.post(
        "/api/auth/register/seeker",
        json={"full_name": "Avatar User", "email": "avatar.user@gmail.com", "password": "correcthorse"},
    )
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"12345678" + b"\xff\xd8\xff\x00"
    res = client.post(
        "/api/seekers/me/profile-picture",
        files={"file": ("avatar.png", image_bytes, "image/png")},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["profile_picture_filename"] == "avatar.png"
    assert body["profile_picture_url"].startswith("/")
    assert body["profile_picture_url"].endswith(".png")
    assert "\\" not in body["profile_picture_url"]
    image_response = client.get(body["profile_picture_url"])
    assert image_response.status_code == 200
    assert image_response.content == image_bytes


def test_require_role_returns_id_for_matching_role():
    dependency = require_role("seeker")
    assert dependency(account={"role": "seeker", "id": 3}) == 3


def test_require_role_rejects_wrong_role():
    dependency = require_role("seeker")
    with pytest.raises(HTTPException) as exc_info:
        dependency(account={"role": "employer", "id": 3})
    assert exc_info.value.status_code == 401


def test_require_role_uses_custom_message():
    dependency = require_role("seeker", "Must be logged in as a job seeker.")
    with pytest.raises(HTTPException) as exc_info:
        dependency(account={"role": "admin", "id": 1})
    assert exc_info.value.detail == "Must be logged in as a job seeker."
