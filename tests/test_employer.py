"""
Acceptance tests for Teammate A's user stories (employer job management).

Style follows tests/test_seeker.py: Given/When/Then docstrings, FastAPI's
TestClient against a throwaway SQLite DB (see conftest.py).
"""

from job_portal.models import Job


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
    r = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload())
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    assert body["skills_required"] == ["Python", "FastAPI"]
    assert body["employer_id"] == 1


def test_create_job_requires_at_least_one_skill(client):
    """
    US-31: Specify skill requirements when creating a job posting

    Given a job with an empty skills list
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    r = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload(skills_required=[]))
    assert r.status_code == 422


def test_create_job_rejects_short_description(client):
    """
    Given a description under 20 characters
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    r = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload(description="too short"))
    assert r.status_code == 422


def test_create_job_rejects_duplicate_title_for_same_employer(client):
    """
    Given employer 1 already has a job titled "Backend Engineer"
    When they POST another job with the same title (any case)
    Then I receive 409 Conflict
    """
    client.post("/api/employer/jobs?employer_id=1", json=_valid_payload())
    r = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload(title="backend engineer"))
    assert r.status_code == 409


def test_create_job_allows_same_title_for_different_employer(client):
    """
    Given employer 1 has a job titled "Backend Engineer"
    When employer 2 creates a job with the SAME title
    Then it succeeds — duplicate-title checks are scoped per employer
    """
    client.post("/api/employer/jobs?employer_id=1", json=_valid_payload())
    r = client.post("/api/employer/jobs?employer_id=2", json=_valid_payload())
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
    client.post("/api/employer/jobs?employer_id=1", json=_valid_payload())
    r = client.get("/api/employer/jobs?employer_id=1")
    assert r.status_code == 200
    jobs = r.json()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "draft"


def test_list_employer_jobs_scoped_to_employer(client):
    """
    Given jobs exist for employer 1 and employer 2
    When employer 2 lists their jobs
    Then only employer 2's job is returned
    """
    client.post("/api/employer/jobs?employer_id=1", json=_valid_payload())
    client.post("/api/employer/jobs?employer_id=2", json=_valid_payload(title="Data Analyst"))
    r = client.get("/api/employer/jobs?employer_id=2")
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
    draft = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload()).json()
    published = client.post(
        "/api/employer/jobs?employer_id=1", json=_valid_payload(title="Data Analyst")
    ).json()
    client.post(f"/api/employer/jobs/{published['id']}/publish?employer_id=1")

    r = client.get("/api/employer/jobs?employer_id=1&status=open")
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
    created = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload()).json()
    updated_payload = _valid_payload(
        title="Senior Backend Engineer", location="Kuala Lumpur", skills_required=["Python", "SQL"]
    )
    r = client.put(f"/api/employer/jobs/{created['id']}?employer_id=1", json=updated_payload)
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
    r = client.put("/api/employer/jobs/999?employer_id=1", json=_valid_payload())
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
    created = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload()).json()
    r = client.post(f"/api/employer/jobs/{created['id']}/publish?employer_id=1")
    assert r.status_code == 200
    assert r.json()["status"] == "open"


def test_close_moves_open_to_closed(client):
    """
    Given an open posting
    When I POST /api/employer/jobs/{id}/close
    Then its status becomes "closed"
    """
    created = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload()).json()
    client.post(f"/api/employer/jobs/{created['id']}/publish?employer_id=1")
    r = client.post(f"/api/employer/jobs/{created['id']}/close?employer_id=1")
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
    created = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload()).json()
    r = client.delete(f"/api/employer/jobs/{created['id']}?employer_id=1")
    assert r.status_code == 204

    listing = client.get("/api/employer/jobs?employer_id=1")
    assert listing.json() == []


def test_delete_missing_job_returns_404(client):
    """
    Given no job with id 999 exists
    When I DELETE /api/employer/jobs/999
    Then I receive 404 Not Found
    """
    r = client.delete("/api/employer/jobs/999?employer_id=1")
    assert r.status_code == 404


def test_cannot_delete_another_employers_job(client):
    """
    Given a job posting belongs to employer 1
    When employer 2 tries to delete it
    Then I receive 404 Not Found (scoped lookup, not a generic 403)
    """
    created = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload()).json()
    r = client.delete(f"/api/employer/jobs/{created['id']}?employer_id=2")
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
    r = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload(title="123"))
    assert r.status_code == 422


def test_rejects_repeated_character_title(client):
    """
    Given a title that's a short pattern repeated to pad length ("bananana...")
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    r = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload(title="ababababab"))
    assert r.status_code == 422


def test_rejects_repeated_character_description(client):
    """
    Given a description that's just a digit pattern repeated ("123123123...")
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    r = client.post(
        "/api/employer/jobs?employer_id=1",
        json=_valid_payload(description="123123123123123123123123123123"),
    )
    assert r.status_code == 422


def test_rejects_single_word_repeated_as_description(client):
    """
    Given a description that repeats one real word instead of describing the role
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    r = client.post(
        "/api/employer/jobs?employer_id=1",
        json=_valid_payload(description="work work work work work work work"),
    )
    assert r.status_code == 422


def test_rejects_numeric_skill(client):
    """
    Given a skill that's just digits
    When I POST /api/employer/jobs
    Then I receive 422 Unprocessable Entity
    """
    r = client.post(
        "/api/employer/jobs?employer_id=1",
        json=_valid_payload(skills_required=["Python", "123"]),
    )
    assert r.status_code == 422


def test_accepts_genuine_looking_content(client):
    """
    Given realistic title/description/skills
    When I POST /api/employer/jobs
    Then it's accepted — the gibberish filter shouldn't false-positive on real content
    """
    r = client.post("/api/employer/jobs?employer_id=1", json=_valid_payload())
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

    created = client.post(
        "/api/employer/jobs?employer_id=1", json=_valid_payload(positions_available=1)
    ).json()
    client.post(f"/api/employer/jobs/{created['id']}/publish?employer_id=1")

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

    job_after = client.get(f"/api/employer/jobs/{created['id']}?employer_id=1").json()
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

    created = client.post(
        "/api/employer/jobs?employer_id=1", json=_valid_payload(positions_available=2)
    ).json()
    client.post(f"/api/employer/jobs/{created['id']}/publish?employer_id=1")

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

    job_after = client.get(f"/api/employer/jobs/{created['id']}?employer_id=1").json()
    assert job_after["positions_filled"] == 1
    assert job_after["status"] == "open"