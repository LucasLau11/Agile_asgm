from job_portal.models import Employer, SeekerProfile
from job_portal.services.auth import hash_password


def _login_admin(client, db_session, tag="1"):
    """Seeds a fresh admin account directly (no admin-registration endpoint
    exists by design — admins are provisioned via seed_admin.py) and logs in."""
    from job_portal.models import Admin

    email = f"admin-{tag}@example.com"
    db_session.add(Admin(email=email, hashed_password=hash_password("correcthorse")))
    db_session.commit()
    r = client.post("/api/auth/login", json={"email": email, "password": "correcthorse"})
    assert r.status_code == 200


def _register_seeker(client, tag):
    r = client.post("/api/auth/register/seeker", json={
        "full_name": "Target Seeker", "email": f"seeker-target-{tag}@example.com", "password": "correcthorse",
    })
    return r.json()["id"]


def _register_employer(client, tag):
    r = client.post("/api/auth/register/employer", json={
        "company_name": "Target Co", "email": f"employer-target-{tag}@example.com", "password": "correcthorse",
    })
    return r.json()["id"]


# ---------------------------------------------------------------------------
# Access control — every endpoint requires a real admin session
# ---------------------------------------------------------------------------

def test_list_seekers_requires_admin(client):
    r = client.get("/api/admin/seekers")
    assert r.status_code == 401


def test_list_seekers_rejects_seeker_session(client, db_session):
    _register_seeker(client, "noaccess")
    r = client.get("/api/admin/seekers")
    assert r.status_code == 401


def test_list_seekers_rejects_employer_session(client, db_session):
    _register_employer(client, "noaccess")
    r = client.get("/api/admin/seekers")
    assert r.status_code == 401


def test_delete_seeker_requires_admin(client, db_session):
    seeker_id = _register_seeker(client, "protected")
    client.post("/api/auth/logout")
    r = client.delete(f"/api/admin/seekers/{seeker_id}")
    assert r.status_code == 401


def test_delete_seeker_rejects_seeker_session(client, db_session):
    _register_seeker(client, "acl-del-seeker")
    r = client.delete("/api/admin/seekers/999999")
    assert r.status_code == 401


def test_delete_seeker_rejects_employer_session(client, db_session):
    _register_employer(client, "acl-del-seeker")
    r = client.delete("/api/admin/seekers/999999")
    assert r.status_code == 401


def test_list_employers_requires_admin(client):
    r = client.get("/api/admin/employers")
    assert r.status_code == 401


def test_list_employers_rejects_seeker_session(client, db_session):
    _register_seeker(client, "acl-list-employers")
    r = client.get("/api/admin/employers")
    assert r.status_code == 401


def test_list_employers_rejects_employer_session(client, db_session):
    _register_employer(client, "acl-list-employers")
    r = client.get("/api/admin/employers")
    assert r.status_code == 401


def test_delete_employer_requires_admin(client, db_session):
    employer_id = _register_employer(client, "acl-del-employer-anon")
    client.post("/api/auth/logout")
    r = client.delete(f"/api/admin/employers/{employer_id}")
    assert r.status_code == 401


def test_delete_employer_rejects_seeker_session(client, db_session):
    _register_seeker(client, "acl-del-employer")
    r = client.delete("/api/admin/employers/999999")
    assert r.status_code == 401


def test_delete_employer_rejects_employer_session(client, db_session):
    _register_employer(client, "acl-del-employer")
    r = client.delete("/api/admin/employers/999999")
    assert r.status_code == 401


def test_suspend_seeker_requires_admin(client, db_session):
    r = client.post("/api/admin/seekers/999999/suspend")
    assert r.status_code == 401


def test_suspend_seeker_rejects_seeker_session(client, db_session):
    _register_seeker(client, "acl-sus-seeker")
    r = client.post("/api/admin/seekers/999999/suspend")
    assert r.status_code == 401


def test_suspend_seeker_rejects_employer_session(client, db_session):
    _register_employer(client, "acl-sus-seeker")
    r = client.post("/api/admin/seekers/999999/suspend")
    assert r.status_code == 401


def test_unsuspend_seeker_requires_admin(client, db_session):
    r = client.post("/api/admin/seekers/999999/unsuspend")
    assert r.status_code == 401


def test_unsuspend_seeker_rejects_seeker_session(client, db_session):
    _register_seeker(client, "acl-unsus-seeker")
    r = client.post("/api/admin/seekers/999999/unsuspend")
    assert r.status_code == 401


def test_unsuspend_seeker_rejects_employer_session(client, db_session):
    _register_employer(client, "acl-unsus-seeker")
    r = client.post("/api/admin/seekers/999999/unsuspend")
    assert r.status_code == 401


def test_suspend_employer_requires_admin(client, db_session):
    r = client.post("/api/admin/employers/999999/suspend")
    assert r.status_code == 401


def test_suspend_employer_rejects_seeker_session(client, db_session):
    _register_seeker(client, "acl-sus-employer")
    r = client.post("/api/admin/employers/999999/suspend")
    assert r.status_code == 401


def test_suspend_employer_rejects_employer_session(client, db_session):
    _register_employer(client, "acl-sus-employer")
    r = client.post("/api/admin/employers/999999/suspend")
    assert r.status_code == 401


def test_unsuspend_employer_requires_admin(client, db_session):
    r = client.post("/api/admin/employers/999999/unsuspend")
    assert r.status_code == 401


def test_unsuspend_employer_rejects_seeker_session(client, db_session):
    _register_seeker(client, "acl-unsus-employer")
    r = client.post("/api/admin/employers/999999/unsuspend")
    assert r.status_code == 401


def test_unsuspend_employer_rejects_employer_session(client, db_session):
    _register_employer(client, "acl-unsus-employer")
    r = client.post("/api/admin/employers/999999/unsuspend")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# US-07 — delete a seeker account
# ---------------------------------------------------------------------------

def test_delete_seeker_removes_account_and_blocks_future_login(client, db_session):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Doomed Seeker", "email": "doomed-seeker@example.com", "password": "correcthorse",
    })
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_admin(client, db_session, "del1")
    r = client.delete(f"/api/admin/seekers/{seeker_id}")
    assert r.status_code == 204
    client.post("/api/auth/logout")

    login_attempt = client.post("/api/auth/login", json={
        "email": "doomed-seeker@example.com", "password": "correcthorse",
    })
    assert login_attempt.status_code == 401


def test_delete_seeker_invalidates_their_current_session(client, db_session):
    """
    Given a seeker is actively logged in (holding a valid session)
    When an admin deletes that seeker's account
    Then every Session row for that account is gone from the database —
    not just "the admin list no longer shows them," but the actual
    sessions table, which is the real security property this test exists
    to prove.
    """
    from job_portal.models import Session as SessionModel

    client.post("/api/auth/register/seeker", json={
        "full_name": "Live Session Seeker", "email": "live-session@example.com", "password": "correcthorse",
    })
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    assert db_session.query(SessionModel).filter(
        SessionModel.account_type == "seeker", SessionModel.account_id == seeker_id
    ).count() >= 1  # sanity check: a real session exists before deletion

    _login_admin(client, db_session, "del2")
    client.delete(f"/api/admin/seekers/{seeker_id}")

    remaining_sessions = db_session.query(SessionModel).filter(
        SessionModel.account_type == "seeker", SessionModel.account_id == seeker_id
    ).count()
    assert remaining_sessions == 0


def test_delete_seeker_nonexistent_returns_404(client, db_session):
    _login_admin(client, db_session, "del3")
    r = client.delete("/api/admin/seekers/999999")
    assert r.status_code == 404


def test_delete_seeker_does_not_affect_other_seekers(client, db_session):
    victim_id = _register_seeker(client, "victim")
    client.post("/api/auth/logout")
    survivor_id = _register_seeker(client, "survivor")
    client.post("/api/auth/logout")

    _login_admin(client, db_session, "del4")
    client.delete(f"/api/admin/seekers/{victim_id}")

    remaining = [s["seeker_id"] for s in client.get("/api/admin/seekers").json()]
    assert victim_id not in remaining
    assert survivor_id in remaining


# ---------------------------------------------------------------------------
# US-08 — delete an employer account
# ---------------------------------------------------------------------------

def test_delete_employer_removes_account_and_blocks_future_login(client, db_session):
    client.post("/api/auth/register/employer", json={
        "company_name": "Doomed Co", "email": "doomed-employer@example.com", "password": "correcthorse",
    })
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login_admin(client, db_session, "del5")
    r = client.delete(f"/api/admin/employers/{employer_id}")
    assert r.status_code == 204
    client.post("/api/auth/logout")

    login_attempt = client.post("/api/auth/login", json={
        "email": "doomed-employer@example.com", "password": "correcthorse",
    })
    assert login_attempt.status_code == 401


def test_delete_employer_nonexistent_returns_404(client, db_session):
    _login_admin(client, db_session, "del6")
    r = client.delete("/api/admin/employers/999999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# US-09 — suspend / unsuspend a seeker account
# ---------------------------------------------------------------------------

def test_suspend_seeker_blocks_login(client, db_session):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Suspended Seeker", "email": "suspended-seeker@example.com", "password": "correcthorse",
    })
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_admin(client, db_session, "sus1")
    r = client.post(f"/api/admin/seekers/{seeker_id}/suspend")
    assert r.status_code == 200
    assert r.json()["status"] == "suspended"
    client.post("/api/auth/logout")

    login_attempt = client.post("/api/auth/login", json={
        "email": "suspended-seeker@example.com", "password": "correcthorse",
    })
    assert login_attempt.status_code == 403


def test_suspend_seeker_invalidates_current_session(client, db_session):
    """
    Given a seeker is actively logged in
    When an admin suspends that seeker's account
    Then every Session row for that account is gone — proven against the
    actual sessions table, not just the status field.
    """
    from job_portal.models import Session as SessionModel

    client.post("/api/auth/register/seeker", json={
        "full_name": "Live Suspend Target", "email": "live-suspend@example.com", "password": "correcthorse",
    })
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    assert db_session.query(SessionModel).filter(
        SessionModel.account_type == "seeker", SessionModel.account_id == seeker_id
    ).count() >= 1

    _login_admin(client, db_session, "sus2")
    client.post(f"/api/admin/seekers/{seeker_id}/suspend")

    remaining_sessions = db_session.query(SessionModel).filter(
        SessionModel.account_type == "seeker", SessionModel.account_id == seeker_id
    ).count()
    assert remaining_sessions == 0


def test_unsuspend_seeker_allows_login_again(client, db_session):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Reinstated Seeker", "email": "reinstated-seeker@example.com", "password": "correcthorse",
    })
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_admin(client, db_session, "sus3")
    client.post(f"/api/admin/seekers/{seeker_id}/suspend")
    r = client.post(f"/api/admin/seekers/{seeker_id}/unsuspend")
    assert r.status_code == 200
    assert r.json()["status"] == "active"
    client.post("/api/auth/logout")

    login_attempt = client.post("/api/auth/login", json={
        "email": "reinstated-seeker@example.com", "password": "correcthorse",
    })
    assert login_attempt.status_code == 200


# ---------------------------------------------------------------------------
# Symmetric employer suspend/unsuspend
# ---------------------------------------------------------------------------

def test_suspend_employer_blocks_login(client, db_session):
    client.post("/api/auth/register/employer", json={
        "company_name": "Suspended Co", "email": "suspended-employer@example.com", "password": "correcthorse",
    })
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login_admin(client, db_session, "sus4")
    r = client.post(f"/api/admin/employers/{employer_id}/suspend")
    assert r.status_code == 200
    assert r.json()["status"] == "suspended"
    client.post("/api/auth/logout")

    login_attempt = client.post("/api/auth/login", json={
        "email": "suspended-employer@example.com", "password": "correcthorse",
    })
    assert login_attempt.status_code == 403


def test_unsuspend_employer_allows_login_again(client, db_session):
    client.post("/api/auth/register/employer", json={
        "company_name": "Reinstated Co", "email": "reinstated-employer@example.com", "password": "correcthorse",
    })
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login_admin(client, db_session, "sus5")
    client.post(f"/api/admin/employers/{employer_id}/suspend")
    r = client.post(f"/api/admin/employers/{employer_id}/unsuspend")
    assert r.status_code == 200
    assert r.json()["status"] == "active"
    client.post("/api/auth/logout")

    login_attempt = client.post("/api/auth/login", json={
        "email": "reinstated-employer@example.com", "password": "correcthorse",
    })
    assert login_attempt.status_code == 200


# ---------------------------------------------------------------------------
# List endpoints — basic shape
# ---------------------------------------------------------------------------

def test_list_seekers_returns_expected_shape(client, db_session):
    _register_seeker(client, "shape")
    client.post("/api/auth/logout")
    _login_admin(client, db_session, "shape1")
    r = client.get("/api/admin/seekers")
    assert r.status_code == 200
    body = r.json()
    assert any(s["email"] == "seeker-target-shape@example.com" for s in body)
    assert all("status" in s for s in body)


def test_list_employers_returns_expected_shape(client, db_session):
    _register_employer(client, "shape")
    client.post("/api/auth/logout")
    _login_admin(client, db_session, "shape2")
    r = client.get("/api/admin/employers")
    assert r.status_code == 200
    body = r.json()
    assert any(e["email"] == "employer-target-shape@example.com" for e in body)
    assert all("status" in e for e in body)


# ---------------------------------------------------------------------------
# Critical 2 — account-id reuse must not leak deleted accounts' data
# ---------------------------------------------------------------------------

def test_deleted_seekers_data_is_not_inherited_by_id_reuse(client, db_session):
    """
    Closes the account-id-reuse disclosure the final review found: deleting
    a seeker must genuinely remove their Application rows, not just the
    account row, because seeker_id gets reissued to the next registrant.
    """
    from job_portal.models import Job

    job = Job(employer_id=1, title="Secret Job", description="x" * 60, status="open")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    client.post("/api/auth/register/seeker", json={
        "full_name": "About To Be Deleted", "email": "reuse-victim@example.com", "password": "correcthorse",
    })
    victim_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/apply", data={"job_id": job.id, "cover_letter": "Hire me"})
    assert client.get("/api/applications").json() != []
    client.post("/api/auth/logout")

    _login_admin(client, db_session, "reuse1")
    client.delete(f"/api/admin/seekers/{victim_id}")
    client.post("/api/auth/logout")

    # Register a fresh seeker — if account ids are reused (they are, by
    # design in register_seeker: next_seeker_id = max + 1), and this new
    # seeker happens to get the deleted victim's old id, they must NOT
    # inherit the victim's application data.
    client.post("/api/auth/register/seeker", json={
        "full_name": "New Registrant", "email": "reuse-newcomer@example.com", "password": "correcthorse",
    })
    new_seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    if new_seeker_id == victim_id:
        assert client.get("/api/applications").json() == []


def test_deleted_employers_jobs_are_removed_not_left_public(client, db_session):
    """
    Closes the final review's Important finding: deleting an employer must
    remove their job postings, not leave them live on the public board.
    """
    client.post("/api/auth/register/employer", json={
        "company_name": "Doomed Job Poster", "email": "doomed-poster@example.com", "password": "correcthorse",
    })
    employer_id = client.get("/api/auth/me").json()["id"]
    from job_portal.models import Job
    job = Job(employer_id=employer_id, title="Should Not Survive", description="x" * 60, status="open")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    job_id = job.id
    client.post("/api/auth/logout")

    _login_admin(client, db_session, "reuse2")
    client.delete(f"/api/admin/employers/{employer_id}")

    r = client.get(f"/api/jobs/{job_id}")
    assert r.status_code == 404

    all_jobs = client.get("/api/jobs").json()
    assert not any(j["id"] == job_id for j in all_jobs)


def test_deleting_seeker_removes_their_interview_invites_not_just_messages(client, db_session):
    """
    Closes a regression the final review caught: bulk-deleting Message rows
    bypasses the ORM cascade to InterviewInvite, which would otherwise
    leave a private interview invite (location/notes) attached to a
    message_id that SQLite immediately reissues to an unrelated new
    message — silently leaking it to a different account.
    """
    from job_portal.models import Conversation, InterviewInvite, Message

    client.post("/api/auth/register/seeker", json={
        "full_name": "Interview Target", "email": "interview-target@example.com", "password": "correcthorse",
    })
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    client.post("/api/auth/register/employer", json={
        "company_name": "Interviewer Co", "email": "interviewer-co@example.com", "password": "correcthorse",
    })
    employer_id = client.get("/api/auth/me").json()["id"]

    r = client.post(f"/api/messages/interview-invite?employer_id={employer_id}&seeker_id={seeker_id}", json={
        "scheduled_at": "2026-09-01T10:00:00",
        "duration_minutes": 30,
        "mode": "video",
        "location_or_link": "https://example.com/room/secret",
        "notes": "confidential",
    })
    assert r.status_code == 200
    message_id = r.json()["id"]
    assert db_session.query(InterviewInvite).filter(InterviewInvite.message_id == message_id).count() == 1
    client.post("/api/auth/logout")

    _login_admin(client, db_session, "invite1")
    client.delete(f"/api/admin/seekers/{seeker_id}")

    assert db_session.query(Message).filter(Message.id == message_id).count() == 0
    assert db_session.query(InterviewInvite).filter(InterviewInvite.message_id == message_id).count() == 0
