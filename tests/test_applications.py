from job_portal.models import Application, Job


def _login_new_employer(client, tag, company_name="Test Co"):
    client.post("/api/auth/register/employer", json={
        "company_name": company_name,
        "email": f"employer-{tag}@example.com",
        "password": "correcthorse",
    })


def _login_new_seeker(client, tag, full_name="Test Seeker"):
    client.post("/api/auth/register/seeker", json={
        "full_name": full_name,
        "email": f"seeker-{tag}@example.com",
        "password": "correcthorse",
    })


def _seed_application(db_session, employer_id, tag="A"):
    """Creates a Job owned by employer_id and one Application against it,
    returning (job, application)."""
    job = Job(employer_id=employer_id, title=f"Role {tag}", description="x" * 60, status="open")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    application = Application(
        seeker_id=1,
        seeker_name="Applicant",
        job_id=job.id,
        job_title=job.title,
        company_name="Test Co",
        skills="Python",
        status="Applied",
        applied_date="1 January 2026",
        email="applicant@example.com",
        cover_letter="I would love this role.",
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return job, application


# ---------------------------------------------------------------------------
# GET /api/employer/applications
# ---------------------------------------------------------------------------


def test_employer_applications_requires_login(client):
    r = client.get("/api/employer/applications")
    assert r.status_code == 401


def test_employer_applications_rejects_seeker_session(client):
    _login_new_seeker(client, "noaccess")
    r = client.get("/api/employer/applications")
    assert r.status_code == 401


def test_employer_applications_scoped_to_own_jobs(client, db_session):
    """
    Given applications exist for employer A's job and employer B's job
    When employer A lists their applications
    Then only their own job's applicant is returned
    """
    _login_new_employer(client, "listA", company_name="Company A")
    employer_a_id = client.get("/api/auth/me").json()["id"]
    job_a, app_a = _seed_application(db_session, employer_a_id, "A")

    _login_new_employer(client, "listB", company_name="Company B")
    employer_b_id = client.get("/api/auth/me").json()["id"]
    _seed_application(db_session, employer_b_id, "B")
    client.post("/api/auth/logout")

    # Log back into employer A's real account (not a new registration) to
    # check what THEY see.
    r = client.post("/api/auth/login", json={
        "email": "employer-listA@example.com", "password": "correcthorse",
    })
    assert r.status_code == 200

    r = client.get("/api/employer/applications")
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    assert results[0]["job_title"] == "Role A"


# ---------------------------------------------------------------------------
# GET /api/employer/applicant/{id} — previously had NO auth at all
# ---------------------------------------------------------------------------


def test_applicant_detail_requires_login(client, db_session):
    _login_new_employer(client, "detailowner")
    employer_id = client.get("/api/auth/me").json()["id"]
    _, app = _seed_application(db_session, employer_id)
    client.post("/api/auth/logout")

    r = client.get(f"/api/employer/applicant/{app.id}")
    assert r.status_code == 401


def test_applicant_detail_rejects_seeker_session(client, db_session):
    _login_new_employer(client, "detailowner2")
    employer_id = client.get("/api/auth/me").json()["id"]
    _, app = _seed_application(db_session, employer_id)
    client.post("/api/auth/logout")

    _login_new_seeker(client, "notemployer")
    r = client.get(f"/api/employer/applicant/{app.id}")
    assert r.status_code == 401


def test_cannot_view_another_employers_applicant(client, db_session):
    """
    Given an applicant belongs to a job owned by employer A
    When employer B requests that applicant's detail by its real id
    Then it 404s — this is the endpoint that previously had NO protection
    at all, so this test is the direct proof the gap is closed.
    """
    _login_new_employer(client, "victimEmployer", company_name="Victim Co")
    victim_id = client.get("/api/auth/me").json()["id"]
    _, app = _seed_application(db_session, victim_id)
    client.post("/api/auth/logout")

    _login_new_employer(client, "attackerEmployer", company_name="Attacker Co")
    r = client.get(f"/api/employer/applicant/{app.id}")
    assert r.status_code == 404


def test_owner_can_view_their_applicant(client, db_session):
    _login_new_employer(client, "detailowner3")
    employer_id = client.get("/api/auth/me").json()["id"]
    _, app = _seed_application(db_session, employer_id)

    r = client.get(f"/api/employer/applicant/{app.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == app.id
    assert body["seeker_id"] == app.seeker_id
    assert body["cover_letter"] == "I would love this role."


# ---------------------------------------------------------------------------
# POST /api/employer/applicant/{id}/update — previously had NO auth at all
# ---------------------------------------------------------------------------


def test_update_applicant_stage_requires_login(client, db_session):
    _login_new_employer(client, "updateowner")
    employer_id = client.get("/api/auth/me").json()["id"]
    _, app = _seed_application(db_session, employer_id)
    client.post("/api/auth/logout")

    r = client.post(f"/api/employer/applicant/{app.id}/update", json={"stage": "Screening"})
    assert r.status_code == 401


def test_cannot_update_another_employers_applicant(client, db_session):
    """
    Given an applicant belongs to a job owned by employer A
    When employer B tries to move that applicant's stage
    Then it 404s and the applicant's status is untouched — this is the
    endpoint that previously let ANYONE, logged in or not, move ANY
    applicant to any stage (with real side effects on job.positions_filled
    and auto-close), so this test directly proves that gap is closed.
    """
    _login_new_employer(client, "victimEmployer2", company_name="Victim Co 2")
    victim_id = client.get("/api/auth/me").json()["id"]
    _, app = _seed_application(db_session, victim_id)
    client.post("/api/auth/logout")

    _login_new_employer(client, "attackerEmployer2", company_name="Attacker Co 2")
    r = client.post(f"/api/employer/applicant/{app.id}/update", json={"stage": "Offered"})
    assert r.status_code == 404

    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={
        "email": "employer-victimEmployer2@example.com", "password": "correcthorse",
    })
    assert r.status_code == 200
    detail = client.get(f"/api/employer/applicant/{app.id}").json()
    assert detail["status"] == "Applied"  # untouched by the attacker's attempt


def test_owner_can_update_their_applicant_stage(client, db_session):
    _login_new_employer(client, "updateowner2")
    employer_id = client.get("/api/auth/me").json()["id"]
    _, app = _seed_application(db_session, employer_id)

    r = client.post(f"/api/employer/applicant/{app.id}/update", json={"stage": "Interview"})
    assert r.status_code == 200
    assert r.json()["status"] == "Interview"


# ---------------------------------------------------------------------------
# GET /api/notifications (role-agnostic)
# ---------------------------------------------------------------------------


def test_get_notifications_requires_login(client):
    r = client.get("/api/notifications")
    assert r.status_code == 401


def test_seeker_sees_only_their_own_notifications(client, db_session):
    from job_portal.models import Notification

    _login_new_seeker(client, "notifseekerA")
    seeker_a_id = client.get("/api/seekers/me").json()["seeker_id"]
    db_session.add(Notification(seeker_id=seeker_a_id, title="For A", message="msg"))
    db_session.add(Notification(seeker_id=999, title="For someone else", message="msg"))
    db_session.commit()

    r = client.get("/api/notifications")
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    assert results[0]["title"] == "For A"


def test_employer_sees_only_their_own_notifications(client, db_session):
    from job_portal.models import Notification

    _login_new_employer(client, "notifemployerA")
    employer_a_id = client.get("/api/auth/me").json()["id"]
    db_session.add(Notification(employer_id=employer_a_id, title="For Employer A", message="msg"))
    db_session.add(Notification(employer_id=999, title="For someone else", message="msg"))
    db_session.commit()

    r = client.get("/api/notifications")
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    assert results[0]["title"] == "For Employer A"


def test_employer_notifications_endpoint_no_longer_exists(client):
    """The separate /api/employer/notifications endpoint was consolidated
    into the role-agnostic /api/notifications in this phase."""
    _login_new_employer(client, "gonecheck")
    r = client.get("/api/employer/notifications")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/notifications/{id} and DELETE /api/notifications
# ---------------------------------------------------------------------------


def test_delete_notification_requires_login(client, db_session):
    from job_portal.models import Notification

    n = Notification(seeker_id=1, title="T", message="M")
    db_session.add(n)
    db_session.commit()
    db_session.refresh(n)

    r = client.delete(f"/api/notifications/{n.id}")
    assert r.status_code == 401


def test_cannot_delete_another_seekers_notification(client, db_session):
    from job_portal.models import Notification

    _login_new_seeker(client, "notifvictim")
    victim_id = client.get("/api/seekers/me").json()["seeker_id"]
    n = Notification(seeker_id=victim_id, title="Victim's", message="M")
    db_session.add(n)
    db_session.commit()
    db_session.refresh(n)
    client.post("/api/auth/logout")

    _login_new_seeker(client, "notifattacker")
    r = client.delete(f"/api/notifications/{n.id}")
    assert r.status_code == 403


def test_owner_can_delete_their_own_notification(client, db_session):
    from job_portal.models import Notification

    _login_new_seeker(client, "notifowner")
    owner_id = client.get("/api/seekers/me").json()["seeker_id"]
    n = Notification(seeker_id=owner_id, title="Mine", message="M")
    db_session.add(n)
    db_session.commit()
    db_session.refresh(n)

    r = client.delete(f"/api/notifications/{n.id}")
    assert r.status_code == 200
    assert client.get("/api/notifications").json() == []


def test_clear_all_notifications_requires_login(client):
    r = client.delete("/api/notifications")
    assert r.status_code == 401


def _seed_admin(db_session, tag="1"):
    """Seeds an Admin account directly (no admin-registration endpoint
    exists by design) and returns its email for login."""
    from job_portal.models import Admin
    from job_portal.services.auth import hash_password

    email = f"admin-notif-{tag}@example.com"
    db_session.add(Admin(email=email, hashed_password=hash_password("correcthorse")))
    db_session.commit()
    return email


def test_admin_session_gets_empty_notifications_not_an_employers(client, db_session):
    """
    Closes a bug the final review found: an admin session used to fall
    into the "employer" branch of notification handling, meaning it could
    read a real employer's notifications if the ids happened to collide
    (Admin.id and Employer.id are independent autoincrement sequences).
    """
    from job_portal.models import Notification

    _login_new_employer(client, "adminconfusion")
    employer_id = client.get("/api/auth/me").json()["id"]
    db_session.add(Notification(employer_id=employer_id, title="Employer secret", message="m"))
    db_session.commit()
    client.post("/api/auth/logout")

    admin_email = _seed_admin(db_session, "get")
    client.post("/api/auth/login", json={"email": admin_email, "password": "correcthorse"})

    r = client.get("/api/notifications")
    assert r.status_code == 200
    assert r.json() == []


def test_admin_cannot_delete_or_clear_notifications(client, db_session):
    from job_portal.models import Notification

    _login_new_employer(client, "adminconfusion2")
    employer_id = client.get("/api/auth/me").json()["id"]
    n = Notification(employer_id=employer_id, title="Employer secret", message="m")
    db_session.add(n)
    db_session.commit()
    db_session.refresh(n)
    client.post("/api/auth/logout")

    admin_email = _seed_admin(db_session, "del")
    client.post("/api/auth/login", json={"email": admin_email, "password": "correcthorse"})

    r = client.delete(f"/api/notifications/{n.id}")
    assert r.status_code == 403

    r = client.delete("/api/notifications")
    assert r.status_code == 403


def test_clear_all_only_clears_own_notifications(client, db_session):
    from job_portal.models import Notification

    _login_new_seeker(client, "clearowner")
    owner_id = client.get("/api/seekers/me").json()["seeker_id"]
    db_session.add(Notification(seeker_id=owner_id, title="Mine 1", message="M"))
    db_session.add(Notification(seeker_id=owner_id, title="Mine 2", message="M"))
    db_session.add(Notification(seeker_id=999, title="Someone else's", message="M"))
    db_session.commit()

    r = client.delete("/api/notifications")
    assert r.status_code == 200
    assert r.json()["deleted"] == 2
    assert client.get("/api/notifications").json() == []
