def test_register_seeker_success(client):
    res = client.post("/api/auth/register/seeker", json={
        "full_name": "Test Seeker",
        "email": "test.seeker@example.com",
        "password": "correcthorse",
    })
    assert res.status_code == 201
    body = res.json()
    assert body["role"] == "seeker"
    assert body["email"] == "test.seeker@example.com"
    assert body["display_name"] == "Test Seeker"
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_seeker_duplicate_email_rejected(client):
    payload = {"full_name": "Test Seeker", "email": "dupe@example.com", "password": "correcthorse"}
    first = client.post("/api/auth/register/seeker", json=payload)
    assert first.status_code == 201
    second = client.post("/api/auth/register/seeker", json=payload)
    assert second.status_code == 409


def test_register_employer_duplicate_email_rejected_cross_role(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Test Seeker", "email": "shared@example.com", "password": "correcthorse",
    })
    res = client.post("/api/auth/register/employer", json={
        "company_name": "Test Co", "email": "shared@example.com", "password": "correcthorse",
    })
    assert res.status_code == 409


def test_register_seeker_password_too_short(client):
    res = client.post("/api/auth/register/seeker", json={
        "full_name": "Test Seeker", "email": "short@example.com", "password": "short",
    })
    assert res.status_code == 422


def test_register_seeker_invalid_name_rejected(client):
    res = client.post("/api/auth/register/seeker", json={
        "full_name": "Test123", "email": "badname@example.com", "password": "correcthorse",
    })
    assert res.status_code == 422


def test_register_employer_success(client):
    res = client.post("/api/auth/register/employer", json={
        "company_name": "Test Co",
        "email": "hr@testco.example.com",
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
        "email": "blank@testco.example.com",
        "password": "correcthorse",
    })
    assert res.status_code == 422


def test_login_success(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Login Test", "email": "login.test@example.com", "password": "correcthorse",
    })
    client.post("/api/auth/logout")  # clear the auto-login session from registration
    res = client.post("/api/auth/login", json={"email": "login.test@example.com", "password": "correcthorse"})
    assert res.status_code == 200
    assert res.json()["email"] == "login.test@example.com"


def test_login_wrong_password_generic_401(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Wrong Pw", "email": "wrongpw@example.com", "password": "correcthorse",
    })
    res = client.post("/api/auth/login", json={"email": "wrongpw@example.com", "password": "incorrect"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect email or password."


def test_login_unknown_email_same_generic_401(client):
    res = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect email or password."


def test_admin_can_log_in(client, db_session):
    from job_portal.models import Admin
    from job_portal.services.auth import hash_password

    admin = Admin(email="admin.test@example.com", hashed_password=hash_password("correcthorse"))
    db_session.add(admin)
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "admin.test@example.com", "password": "correcthorse"})
    assert res.status_code == 200
    assert res.json()["role"] == "admin"


def test_login_rejects_suspended_seeker(client, db_session):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Suspended", "email": "suspended@example.com", "password": "correcthorse",
    })
    client.post("/api/auth/logout")

    from job_portal.models import SeekerProfile
    profile = db_session.query(SeekerProfile).filter(SeekerProfile.email == "suspended@example.com").first()
    profile.status = "suspended"
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "suspended@example.com", "password": "correcthorse"})
    assert res.status_code == 403


def test_login_wrong_password_on_suspended_account_still_generic_401(client, db_session):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Suspended Wrong Pw", "email": "suspended.wrongpw@example.com", "password": "correcthorse",
    })
    client.post("/api/auth/logout")

    from job_portal.models import SeekerProfile
    profile = db_session.query(SeekerProfile).filter(SeekerProfile.email == "suspended.wrongpw@example.com").first()
    profile.status = "suspended"
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "suspended.wrongpw@example.com", "password": "totally-wrong"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Incorrect email or password."


def test_me_requires_session(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_logout_invalidates_session(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Logout Test", "email": "logout.test@example.com", "password": "correcthorse",
    })
    client.post("/api/auth/logout")
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_register_then_me_reflects_logged_in_account(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Me Test", "email": "me.test@example.com", "password": "correcthorse",
    })
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "seeker"
    assert body["email"] == "me.test@example.com"
    assert "hashed_password" not in body


def test_employer_login_success(client):
    client.post("/api/auth/register/employer", json={
        "company_name": "Login Test Co", "email": "employer.login@example.com", "password": "correcthorse",
    })
    client.post("/api/auth/logout")
    res = client.post("/api/auth/login", json={"email": "employer.login@example.com", "password": "correcthorse"})
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "employer"
    assert body["email"] == "employer.login@example.com"


def test_employer_login_rejects_suspended(client, db_session):
    client.post("/api/auth/register/employer", json={
        "company_name": "Suspended Co", "email": "employer.suspended@example.com", "password": "correcthorse",
    })
    client.post("/api/auth/logout")

    from job_portal.models import Employer
    employer = db_session.query(Employer).filter(Employer.email == "employer.suspended@example.com").first()
    employer.status = "suspended"
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "employer.suspended@example.com", "password": "correcthorse"})
    assert res.status_code == 403


def test_register_employer_then_me_reflects_logged_in_account(client):
    client.post("/api/auth/register/employer", json={
        "company_name": "Me Test Co", "email": "employer.me@example.com", "password": "correcthorse",
    })
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "employer"
    assert body["email"] == "employer.me@example.com"
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

    legacy = SeekerProfile(seeker_id=9001, full_name="Legacy", email="shared.email@example.com", skills="")
    db_session.add(legacy)
    real = SeekerProfile(
        seeker_id=9002, full_name="Real Account", email="shared.email@example.com",
        hashed_password=hash_password("correcthorse"), status="active", skills="",
    )
    db_session.add(real)
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "shared.email@example.com", "password": "correcthorse"})
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
        email="aisha.rahman@example.com",
        phone="012-345 6789",
        bio="Backend-leaning full-stack developer.",
        skills="Python,FastAPI,SQL,Docker",
        hashed_password=hash_password("password123"),
        status="active",
    )
    db_session.add(seeded)
    db_session.commit()

    res = client.post("/api/auth/login", json={"email": "aisha.rahman@example.com", "password": "password123"})
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "seeker"
    assert body["display_name"] == "Aisha Rahman"
