"""
Acceptance tests for Teammate A's user stories (employer job management).

Style follows tests/test_seeker.py: Given/When/Then docstrings, FastAPI's
TestClient against a throwaway SQLite DB (see conftest.py).
"""

from job_portal.models import Job


def _login_new_employer(client, tag, company_name="Test Co"):
    """Registers and logs in a fresh employer account for test isolation —
    mirrors _login_new_seeker in test_seeker.py."""
    client.post("/api/auth/register/employer", json={
        "company_name": company_name,
        "email": f"employer-{tag}@example.com",
        "password": "correcthorse",
    })


def _valid_payload(**overrides):
    payload = {
        "title": "Backend Engineer",
        "location": "Penang",
        "state": "Penang",
        "job_type": "Full-time",
        "salary_min": 4000,
        "salary_max": 6000,
        "skills_required": ["Python", "FastAPI"],
        "description": "Build and maintain our backend services using Python and FastAPI.",
        "positions_available": 2,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# US-27 / US-31: Create a job posting with required skills
# ---------------------------------------------------------------------------


def test_create_job_starts_as_draft(client):
    """
    US-27: Create job postings

    Given valid job details including required skills
    When I POST /api/employer/jobs
    Then the posting is created with status "draft" and the skills saved
    """
    _login_new_employer(client, "1")
    employer_id = client.get("/api/auth/me").json()["id"]
    r = client.post("/api/employer/jobs", json=_valid_payload())
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    assert body["skills_required"] == ["Python", "FastAPI"]
    assert body["employer_id"] == employer_id


def test_create_job_requires_at_least_one_skill(client):
    """
    US-31: Specify skill requirements when creating a job posting

    Given a job with an empty skills list
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    _login_new_employer(client, "2")
    r = client.post("/api/employer/jobs", json=_valid_payload(skills_required=[]))
    assert r.status_code == 422


def test_create_job_rejects_short_description(client):
    """
    Given a description under 20 characters
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    _login_new_employer(client, "3")
    r = client.post("/api/employer/jobs", json=_valid_payload(description="too short"))
    assert r.status_code == 422


def test_create_job_rejects_duplicate_title_for_same_employer(client):
    """
    Given employer 1 already has a job titled "Backend Engineer"
    When they POST another job with the same title (any case)
    Then I receive 409 Conflict
    """
    _login_new_employer(client, "4")
    client.post("/api/employer/jobs", json=_valid_payload())
    r = client.post("/api/employer/jobs", json=_valid_payload(title="backend engineer"))
    assert r.status_code == 409


def test_create_job_allows_same_title_for_different_employer(client):
    """
    Given employer A has a job titled "Backend Engineer"
    When employer B creates a job with the SAME title
    Then it succeeds — duplicate-title checks are scoped per employer
    """
    _login_new_employer(client, "dupA", company_name="Company A")
    client.post("/api/employer/jobs", json=_valid_payload())
    client.post("/api/auth/logout")

    _login_new_employer(client, "dupB", company_name="Company B")
    r = client.post("/api/employer/jobs", json=_valid_payload())
    assert r.status_code == 201


# ---------------------------------------------------------------------------
# US-28: View own job postings
# ---------------------------------------------------------------------------


def test_list_employer_jobs_includes_drafts(client):
    """
    US-28: View job postings

    Given an employer has one draft posting
    When I GET /api/employer/jobs
    Then it's included (unlike the seeker-facing /api/jobs, which hides drafts)
    """
    _login_new_employer(client, "5")
    client.post("/api/employer/jobs", json=_valid_payload())
    r = client.get("/api/employer/jobs")
    assert r.status_code == 200
    jobs = r.json()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "draft"


def test_list_employer_jobs_scoped_to_employer(client):
    """
    Given jobs exist for employer A and employer B
    When employer B lists their jobs
    Then only employer B's job is returned
    """
    _login_new_employer(client, "scopeA", company_name="Company A")
    client.post("/api/employer/jobs", json=_valid_payload())
    client.post("/api/auth/logout")

    _login_new_employer(client, "scopeB", company_name="Company B")
    client.post("/api/employer/jobs", json=_valid_payload(title="Data Analyst"))
    r = client.get("/api/employer/jobs")
    assert r.status_code == 200
    jobs = r.json()
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Data Analyst"


def test_list_employer_jobs_filters_by_status(client):
    """
    Given a draft and a published job both exist
    When I filter by status=open
    Then only the published one is returned
    """
    _login_new_employer(client, "6")
    draft = client.post("/api/employer/jobs", json=_valid_payload()).json()
    published = client.post(
        "/api/employer/jobs", json=_valid_payload(title="Data Analyst")
    ).json()
    client.post(f"/api/employer/jobs/{published['id']}/publish")

    r = client.get("/api/employer/jobs?status=open")
    assert r.status_code == 200
    jobs = r.json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == published["id"]


# ---------------------------------------------------------------------------
# US-29 / US-32: Update a job posting (including skills)
# ---------------------------------------------------------------------------


def test_update_job_changes_fields_and_skills(client):
    """
    US-29 / US-32: Update job postings + skill requirements

    Given an existing draft posting
    When I PUT /api/employer/jobs/{id} with new title/location/skills
    Then the posting reflects the new values
    """
    _login_new_employer(client, "7")
    created = client.post("/api/employer/jobs", json=_valid_payload()).json()
    updated_payload = _valid_payload(
        title="Senior Backend Engineer", location="Kuala Lumpur", skills_required=["Python", "SQL"]
    )
    r = client.put(f"/api/employer/jobs/{created['id']}", json=updated_payload)
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Senior Backend Engineer"
    assert body["location"] == "Kuala Lumpur"
    assert body["skills_required"] == ["Python", "SQL"]


def test_update_missing_job_returns_404(client):
    """
    Given no job with id 999 exists
    When I PUT /api/employer/jobs/999
    Then I receive 404 Not Found
    """
    _login_new_employer(client, "8")
    r = client.put("/api/employer/jobs/999", json=_valid_payload())
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Publish / close
# ---------------------------------------------------------------------------


def test_publish_moves_draft_to_open(client):
    """
    Given a draft posting
    When I POST /api/employer/jobs/{id}/publish
    Then its status becomes "open"
    """
    _login_new_employer(client, "9")
    created = client.post("/api/employer/jobs", json=_valid_payload()).json()
    r = client.post(f"/api/employer/jobs/{created['id']}/publish")
    assert r.status_code == 200
    assert r.json()["status"] == "open"


def test_close_moves_open_to_closed(client):
    """
    Given an open posting
    When I POST /api/employer/jobs/{id}/close
    Then its status becomes "closed"
    """
    _login_new_employer(client, "10")
    created = client.post("/api/employer/jobs", json=_valid_payload()).json()
    client.post(f"/api/employer/jobs/{created['id']}/publish")
    r = client.post(f"/api/employer/jobs/{created['id']}/close")
    assert r.status_code == 200
    assert r.json()["status"] == "closed"


# ---------------------------------------------------------------------------
# US-30: Delete a job posting
# ---------------------------------------------------------------------------


def test_delete_draft_job(client, db_session):
    """
    US-30: Delete job postings

    Given a draft posting exists
    When I DELETE /api/employer/jobs/{id}
    Then it's removed and no longer listed
    """
    _login_new_employer(client, "11")
    created = client.post("/api/employer/jobs", json=_valid_payload()).json()
    r = client.delete(f"/api/employer/jobs/{created['id']}")
    assert r.status_code == 204

    listing = client.get("/api/employer/jobs")
    assert listing.json() == []


def test_delete_missing_job_returns_404(client):
    """
    Given no job with id 999 exists
    When I DELETE /api/employer/jobs/999
    Then I receive 404 Not Found
    """
    _login_new_employer(client, "12")
    r = client.delete("/api/employer/jobs/999")
    assert r.status_code == 404


def test_delete_job_removes_its_applications(client, db_session):
    """
    Given a job has an application against it
    When the employer deletes the job posting
    Then the Application row is genuinely gone, not just orphaned
    """
    from job_portal.models import Application

    _login_new_employer(client, "delapp1")
    created = client.post("/api/employer/jobs", json=_valid_payload()).json()

    application = Application(
        seeker_id=1,
        seeker_name="Test Seeker",
        job_id=created["id"],
        job_title=created["title"],
        company_name="Test Co",
        skills="Python",
        status="Applied",
        applied_date="1 January 2026",
        email="test@example.com",
    )
    db_session.add(application)
    db_session.commit()
    app_id = application.id

    r = client.delete(f"/api/employer/jobs/{created['id']}")
    assert r.status_code == 204

    remaining = db_session.query(Application).filter(Application.id == app_id).first()
    assert remaining is None


def test_deleted_jobs_applicants_are_not_inherited_by_id_reuse(client, db_session):
    """
    Closes the disclosure the final review found: after a job is deleted
    and a DIFFERENT employer's new job happens to reuse the freed id, that
    employer must NOT be able to see or mutate the original applicant.
    """
    from job_portal.models import Application

    _login_new_employer(client, "reuseA", company_name="Company A")
    job_a = client.post("/api/employer/jobs", json=_valid_payload()).json()

    application = Application(
        seeker_id=1,
        seeker_name="Confidential Applicant",
        job_id=job_a["id"],
        job_title=job_a["title"],
        company_name="Company A",
        skills="Python",
        status="Applied",
        applied_date="1 January 2026",
        email="confidential@example.com",
        cover_letter="CONFIDENTIAL",
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    app_id = application.id

    client.delete(f"/api/employer/jobs/{job_a['id']}")
    client.post("/api/auth/logout")

    _login_new_employer(client, "reuseB", company_name="Company B")
    job_b = client.post("/api/employer/jobs", json=_valid_payload(title="Unrelated Role")).json()

    if job_b["id"] == job_a["id"]:
        # The id was genuinely reused — this is the exact scenario the fix closes.
        r = client.get(f"/api/employer/applicant/{app_id}")
        assert r.status_code == 404
    else:
        # SQLite didn't happen to reuse the id in this run — the application
        # row is still gone either way (proven by test_delete_job_removes_its_applications),
        # so there's nothing left that COULD be inherited.
        remaining = db_session.query(Application).filter(Application.id == app_id).first()
        assert remaining is None


def test_cannot_delete_another_employers_job(client):
    """
    Given a job posting belongs to employer A
    When employer B tries to delete it
    Then I receive 404 Not Found (scoped lookup, not a generic 403) — B's
    session can't reach A's job no matter what id they guess
    """
    _login_new_employer(client, "delA", company_name="Company A")
    created = client.post("/api/employer/jobs", json=_valid_payload()).json()
    client.post("/api/auth/logout")

    _login_new_employer(client, "delB", company_name="Company B")
    r = client.delete(f"/api/employer/jobs/{created['id']}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Content-quality validation ("nonsense" filter)
# ---------------------------------------------------------------------------


def test_rejects_purely_numeric_title(client):
    """
    Given a title that's just digits
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    _login_new_employer(client, "13")
    r = client.post("/api/employer/jobs", json=_valid_payload(title="123"))
    assert r.status_code == 422


def test_rejects_repeated_character_title(client):
    """
    Given a title that's a short pattern repeated to pad length ("bananana...")
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    _login_new_employer(client, "14")
    r = client.post("/api/employer/jobs", json=_valid_payload(title="ababababab"))
    assert r.status_code == 422


def test_rejects_repeated_character_description(client):
    """
    Given a description that's just a digit pattern repeated ("123123123...")
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    _login_new_employer(client, "15")
    r = client.post(
        "/api/employer/jobs",
        json=_valid_payload(description="123123123123123123123123123123"),
    )
    assert r.status_code == 422


def test_rejects_single_word_repeated_as_description(client):
    """
    Given a description that repeats one real word instead of describing the role
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    _login_new_employer(client, "16")
    r = client.post(
        "/api/employer/jobs",
        json=_valid_payload(description="work work work work work work work"),
    )
    assert r.status_code == 422


def test_rejects_numeric_skill(client):
    """
    Given a skill that's just digits
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    _login_new_employer(client, "17")
    r = client.post(
        "/api/employer/jobs",
        json=_valid_payload(skills_required=["Python", "123"]),
    )
    assert r.status_code == 422


def test_accepts_genuine_looking_content(client):
    """
    Given realistic title/description/skills
    When I POST /api/employer/jobs
    Then it's accepted — the gibberish filter shouldn't false-positive on real content
    """
    _login_new_employer(client, "18")
    r = client.post("/api/employer/jobs", json=_valid_payload())
    assert r.status_code == 201


# ---------------------------------------------------------------------------
# Auto-close when positions fill up (triggered from the applications side)
# ---------------------------------------------------------------------------


def test_job_auto_closes_when_last_position_offered(client, db_session):
    """
    Given a job with 1 position available, already published (open)
    And a seeker has applied
    When the employer moves that applicant's stage to "Offered"
    Then positions_filled becomes 1 and the job auto-closes
    """
    from job_portal.models import Application

    _login_new_employer(client, "19")
    created = client.post(
        "/api/employer/jobs", json=_valid_payload(positions_available=1)
    ).json()
    client.post(f"/api/employer/jobs/{created['id']}/publish")

    application = Application(
        seeker_id=1,
        seeker_name="Test Seeker",
        job_id=created["id"],
        job_title=created["title"],
        company_name="Test Co",
        skills="Python",
        status="Applied",
        applied_date="1 January 2026",
        email="test@example.com",
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    r = client.post(
        f"/api/employer/applicant/{application.id}/update",
        json={"stage": "Offered"},
    )
    assert r.status_code == 200

    job_after = client.get(f"/api/employer/jobs/{created['id']}").json()
    assert job_after["positions_filled"] == 1
    assert job_after["status"] == "closed"


def test_job_stays_open_when_positions_remain(client, db_session):
    """
    Given a job with 2 positions available, already published
    And one applicant is offered the role
    When I check the job afterward
    Then only 1 position is filled and the job stays open (not auto-closed)
    """
    from job_portal.models import Application

    _login_new_employer(client, "20")
    created = client.post(
        "/api/employer/jobs", json=_valid_payload(positions_available=2)
    ).json()
    client.post(f"/api/employer/jobs/{created['id']}/publish")

    application = Application(
        seeker_id=1,
        seeker_name="Test Seeker",
        job_id=created["id"],
        job_title=created["title"],
        company_name="Test Co",
        skills="Python",
        status="Applied",
        applied_date="1 January 2026",
        email="test@example.com",
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    client.post(f"/api/employer/applicant/{application.id}/update", json={"stage": "Offered"})

    job_after = client.get(f"/api/employer/jobs/{created['id']}").json()
    assert job_after["positions_filled"] == 1
    assert job_after["status"] == "open"


# ---------------------------------------------------------------------------
# Login / role required on every retrofitted endpoint
# ---------------------------------------------------------------------------


def test_list_employer_jobs_requires_login(client):
    r = client.get("/api/employer/jobs")
    assert r.status_code == 401


def test_list_employer_jobs_rejects_seeker_session(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Not An Employer", "email": "not-employer-list@example.com", "password": "correcthorse",
    })
    r = client.get("/api/employer/jobs")
    assert r.status_code == 401


def test_get_employer_job_requires_login(client):
    r = client.get("/api/employer/jobs/1")
    assert r.status_code == 401


def test_create_job_requires_login(client):
    r = client.post("/api/employer/jobs", json=_valid_payload())
    assert r.status_code == 401


def test_create_job_rejects_seeker_session(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Not An Employer", "email": "not-employer-create@example.com", "password": "correcthorse",
    })
    r = client.post("/api/employer/jobs", json=_valid_payload())
    assert r.status_code == 401


def test_update_job_requires_login(client):
    r = client.put("/api/employer/jobs/1", json=_valid_payload())
    assert r.status_code == 401


def test_publish_job_requires_login(client):
    r = client.post("/api/employer/jobs/1/publish")
    assert r.status_code == 401


def test_close_job_requires_login(client):
    r = client.post("/api/employer/jobs/1/close")
    assert r.status_code == 401


def test_delete_job_requires_login(client):
    r = client.delete("/api/employer/jobs/1")
    assert r.status_code == 401