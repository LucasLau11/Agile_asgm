"""
Acceptance tests for Teammate B's user stories.

Style follows the tutor's demo repo: Given/When/Then docstrings on each
test, using FastAPI's TestClient against a throwaway SQLite DB (see
conftest.py). One test per user story's happy path, plus a few negative
cases — mirrors the "basic + negative + parametrized" structure from
tests/test_acceptance_items.py in the teaching template.
"""

import io

from job_portal.models import Job

# ---------------------------------------------------------------------------
# US-20: View job postings
# ---------------------------------------------------------------------------


def test_list_jobs_returns_open_postings(client, sample_job):
    """
    US-20: View job postings

    Given a job posting exists
    When I GET /api/jobs
    Then I receive it in the list with its skills and credibility score
    """
    r = client.get("/api/jobs")
    assert r.status_code == 200
    jobs = r.json()
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Backend Engineer"
    assert "Python" in jobs[0]["skills_required"]
    assert jobs[0]["credibility_score"] is not None


def test_list_jobs_empty_when_no_postings(client):
    """
    US-20: View job postings (empty state)

    Given no job postings exist
    When I GET /api/jobs
    Then I receive an empty list, not an error
    """
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# US-12: Search jobs by keyword
# ---------------------------------------------------------------------------


def test_search_by_keyword_matches_title(client, sample_job):
    """
    US-12: Search jobs using keywords

    Given a job titled "Backend Engineer" exists
    When I GET /api/jobs?keyword=backend (case-insensitive, partial)
    Then that job is returned
    """
    r = client.get("/api/jobs?keyword=backend")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_search_by_keyword_no_match_returns_empty(client, sample_job):
    """
    US-12: Search jobs using keywords (no match)

    Given only a "Backend Engineer" job exists
    When I search for a keyword that matches nothing
    Then I receive an empty list
    """
    r = client.get("/api/jobs?keyword=nonexistentrole")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# US-13: Filter jobs by location
# ---------------------------------------------------------------------------


def test_filter_by_location(client, sample_job):
    """
    US-13: Filter jobs by location

    Given a job located in "Penang, Malaysia" exists
    When I GET /api/jobs?location=penang (case-insensitive, partial)
    Then that job is returned
    """
    r = client.get("/api/jobs?location=penang")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_keyword_and_location_combine_with_and_logic(client, db_session):
    """
    US-12 + US-13 combined: keyword AND location must both match

    Given two jobs in different locations, only one matching the keyword
    When I search with both a keyword and a location filter
    Then only the job matching BOTH is returned
    """
    db_session.add_all(
        [
            Job(employer_id=1, title="Backend Engineer", description="x" * 60,
                location="Penang", skills_required="Python", status="open"),
            Job(employer_id=1, title="Backend Engineer", description="x" * 60,
                location="Kuala Lumpur", skills_required="Python", status="open"),
        ]
    )
    db_session.commit()

    r = client.get("/api/jobs?keyword=backend&location=penang")
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    assert results[0]["location"] == "Penang"


# ---------------------------------------------------------------------------
# US-21: View job details
# ---------------------------------------------------------------------------


def test_get_job_details(client, sample_job):
    """
    US-21: View detailed job description

    Given a job posting exists
    When I GET /api/jobs/{id}
    Then I receive its full details
    """
    r = client.get(f"/api/jobs/{sample_job.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == sample_job.id
    assert "Build and maintain" in body["description"]


def test_get_missing_job_returns_404(client):
    """
    US-21: View detailed job description (missing job)

    Given no job with ID 999 exists
    When I GET /api/jobs/999
    Then I receive 404 Not Found
    """
    r = client.get("/api/jobs/999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# US-22: Maintain skill profile
# ---------------------------------------------------------------------------


def test_update_skills_creates_profile_on_first_use(client):
    """
    US-22: Maintain skill profile (first-time use, no login yet)

    Given a seeker has never touched their profile before
    When I PUT /api/seekers/{id}/skills with a skill list
    Then a profile is created on the fly and the skills are saved
    """
    r = client.put("/api/seekers/42/skills", json={"skills": ["Python", "SQL"]})
    assert r.status_code == 200
    body = r.json()
    assert body["seeker_id"] == 42
    assert set(body["skills"]) == {"Python", "SQL"}


def test_update_skills_replaces_existing_list(client):
    """
    US-22: Maintain skill profile (update)

    Given a seeker already has skills saved
    When I PUT a new skill list
    Then the old list is fully replaced, not merged
    """
    client.put("/api/seekers/7/skills", json={"skills": ["Python"]})
    r = client.put("/api/seekers/7/skills", json={"skills": ["React", "CSS"]})
    assert r.status_code == 200
    assert set(r.json()["skills"]) == {"React", "CSS"}


def test_update_skills_strips_blank_entries(client):
    """
    US-22: Maintain skill profile (input cleanup)

    Given the frontend sends a skill list with blank/whitespace entries
    When I PUT /api/seekers/{id}/skills
    Then blank entries are dropped rather than stored
    """
    r = client.put("/api/seekers/8/skills", json={"skills": ["Python", "  ", ""]})
    assert r.status_code == 200
    assert r.json()["skills"] == ["Python"]


# ---------------------------------------------------------------------------
# US-03: Upload resume
# ---------------------------------------------------------------------------


def test_upload_resume_pdf_succeeds(client, tmp_path):
    """
    US-03: Upload resume

    Given a seeker has a valid PDF file
    When they POST it to /api/seekers/{id}/resume
    Then it's accepted and the filename is recorded on their profile
    """
    fake_pdf = io.BytesIO(b"%PDF-1.4 fake content for testing")
    r = client.post(
        "/api/seekers/5/resume",
        files={"file": ("resume.pdf", fake_pdf, "application/pdf")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["resume_filename"] == "resume.pdf"
    assert body["resume_url"] is not None


def test_upload_resume_rejects_wrong_file_type(client):
    """
    US-03: Upload resume (validation)

    Given a seeker tries to upload a .jpg file
    When they POST it to /api/seekers/{id}/resume
    Then they receive 400 Bad Request, and no profile change happens
    """
    fake_image = io.BytesIO(b"not a real jpg but wrong content-type is what matters here")
    r = client.post(
        "/api/seekers/5/resume",
        files={"file": ("photo.jpg", fake_image, "image/jpeg")},
    )
    assert r.status_code == 400


def test_upload_resume_rejects_oversized_file(client):
    """
    US-03: Upload resume (size limit)

    Given a seeker tries to upload a PDF larger than 5 MB
    When they POST it to /api/seekers/{id}/resume
    Then they receive 400 Bad Request
    """
    oversized = io.BytesIO(b"0" * (5 * 1024 * 1024 + 1))
    r = client.post(
        "/api/seekers/5/resume",
        files={"file": ("big_resume.pdf", oversized, "application/pdf")},
    )
    assert r.status_code == 400
