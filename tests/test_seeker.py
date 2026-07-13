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


# ---------------------------------------------------------------------------
# Advanced filters: state, job_type, salary range
# ---------------------------------------------------------------------------


def test_filter_by_state(client, db_session):
    """
    Advanced filter: filter jobs by state/region

    Given jobs in different states
    When I filter by state=Penang
    Then only the Penang job is returned
    """
    db_session.add_all([
        Job(employer_id=1, title="Job A", description="x" * 60, state="Penang", status="open"),
        Job(employer_id=1, title="Job B", description="x" * 60, state="Selangor", status="open"),
    ])
    db_session.commit()

    r = client.get("/api/jobs?state=Penang")
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    assert results[0]["title"] == "Job A"


def test_filter_by_job_type(client, db_session):
    """
    Advanced filter: filter jobs by job type

    Given jobs of different types
    When I filter by job_type=Internship
    Then only internship postings are returned
    """
    db_session.add_all([
        Job(employer_id=1, title="Intern role", description="x" * 60, job_type="Internship", status="open"),
        Job(employer_id=1, title="FT role", description="x" * 60, job_type="Full-time", status="open"),
    ])
    db_session.commit()

    r = client.get("/api/jobs?job_type=Internship")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["title"] == "Intern role"


def test_filter_by_salary_range_overlap(client, db_session):
    """
    Advanced filter: salary range uses overlap logic, not strict containment

    Given a job paying RM4000-6000
    When I search for salary_min=5000&salary_max=8000 (only partially overlapping)
    Then the job still shows up, because part of its range fits what I want
    """
    db_session.add(
        Job(employer_id=1, title="Overlapping job", description="x" * 60,
            salary_min=4000, salary_max=6000, status="open")
    )
    db_session.commit()

    r = client.get("/api/jobs?salary_min=5000&salary_max=8000")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_filter_by_salary_range_excludes_non_overlapping(client, db_session):
    """
    Advanced filter: salary range excludes jobs with no overlap at all

    Given a job paying RM1500-2200 (an internship stipend)
    When I search for salary_min=5000&salary_max=8000
    Then that job is excluded
    """
    db_session.add(
        Job(employer_id=1, title="Low paying job", description="x" * 60,
            salary_min=1500, salary_max=2200, status="open")
    )
    db_session.commit()

    r = client.get("/api/jobs?salary_min=5000&salary_max=8000")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Positions remaining ("spots left" display)
# ---------------------------------------------------------------------------


def test_positions_remaining_computed_correctly(client, db_session):
    """
    Given a job with 3 available positions and 1 already filled
    When I fetch that job
    Then positions_remaining is 2 (3 - 1)
    """
    job = Job(employer_id=1, title="Job", description="x" * 60, status="open",
              positions_available=3, positions_filled=1)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    r = client.get(f"/api/jobs/{job.id}")
    assert r.status_code == 200
    assert r.json()["positions_remaining"] == 2


def test_positions_remaining_never_negative(client, db_session):
    """
    Given a job that's somehow over-filled (edge case / data entry error)
    When I fetch that job
    Then positions_remaining floors at 0, not a negative number
    """
    job = Job(employer_id=1, title="Job", description="x" * 60, status="open",
              positions_available=1, positions_filled=5)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    r = client.get(f"/api/jobs/{job.id}")
    assert r.json()["positions_remaining"] == 0


# ---------------------------------------------------------------------------
# Resume/skill-based job matching
# ---------------------------------------------------------------------------


def test_recommended_jobs_scores_by_skill_overlap(client, db_session):
    """
    Given a seeker with skills Python, SQL
    And a job requiring Python, SQL, Docker
    When I fetch recommended jobs for that seeker
    Then the job is returned with a 67% match (2 of 3 required skills)
    """
    client.put("/api/seekers/50/skills", json={"skills": ["Python", "SQL"]})
    db_session.add(
        Job(employer_id=1, title="Matched job", description="x" * 60,
            skills_required="Python,SQL,Docker", status="open")
    )
    db_session.commit()

    r = client.get("/api/jobs/recommended?seeker_id=50")
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    assert results[0]["match_percentage"] == 67


def test_recommended_jobs_excludes_zero_overlap(client, db_session):
    """
    Given a seeker with skills that share nothing with a job's requirements
    When I fetch recommended jobs
    Then that job is excluded entirely (0% match doesn't clear the min_match bar)
    """
    client.put("/api/seekers/51/skills", json={"skills": ["Photoshop"]})
    db_session.add(
        Job(employer_id=1, title="Unrelated job", description="x" * 60,
            skills_required="Python,SQL", status="open")
    )
    db_session.commit()

    r = client.get("/api/jobs/recommended?seeker_id=51")
    assert r.json() == []


def test_recommended_jobs_empty_when_seeker_has_no_skills(client):
    """
    Given a seeker who has never set any skills
    When I fetch recommended jobs
    Then I get an empty list rather than an error
    """
    r = client.get("/api/jobs/recommended?seeker_id=999")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Profile info (name/email/phone/bio)
# ---------------------------------------------------------------------------


def test_update_profile_info(client):
    """
    Given a seeker fills in their personal details
    When I PUT /api/seekers/{id} with name/email/phone/bio
    Then the profile reflects those values
    """
    r = client.put(
        "/api/seekers/60",
        json={"full_name": "Jane Doe", "email": "jane@test.com", "phone": "012-3456789", "bio": "Hello."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "Jane Doe"
    assert body["email"] == "jane@test.com"


# ---------------------------------------------------------------------------
# Work experience
# ---------------------------------------------------------------------------


def test_add_and_delete_experience(client):
    """
    Given a seeker adds a work experience entry
    When I POST then DELETE it
    Then it appears after adding and disappears after deleting
    """
    r = client.post(
        "/api/seekers/61/experience",
        json={"job_title": "Intern", "company_name": "TechCo", "start_date": "2023", "end_date": "2024",
              "description": "Did things."},
    )
    assert r.status_code == 201
    body = r.json()
    assert len(body["experience"]) == 1
    exp_id = body["experience"][0]["id"]

    r2 = client.delete(f"/api/seekers/61/experience/{exp_id}")
    assert r2.status_code == 200
    assert r2.json()["experience"] == []


def test_delete_experience_not_found_returns_404(client):
    """
    Given no experience entry with ID 999 exists for this seeker
    When I try to delete it
    Then I get 404, not a silent success
    """
    r = client.delete("/api/seekers/62/experience/999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------


def test_add_and_delete_education(client):
    """
    Given a seeker adds an education entry
    When I POST then DELETE it
    Then it appears after adding and disappears after deleting
    """
    r = client.post(
        "/api/seekers/63/education",
        json={"institution": "USM", "degree": "BSc", "field_of_study": "CS",
              "start_date": "2019", "end_date": "2023"},
    )
    assert r.status_code == 201
    edu_id = r.json()["education"][0]["id"]

    r2 = client.delete(f"/api/seekers/63/education/{edu_id}")
    assert r2.status_code == 200
    assert r2.json()["education"] == []


# ---------------------------------------------------------------------------
# Security: file upload validation (magic bytes, not spoofable headers)
# ---------------------------------------------------------------------------


def test_upload_rejects_spoofed_content_type(client):
    """
    Security: a file with a fake Content-Type header but non-PDF actual
    content must be rejected

    Given a plain text file
    When it's uploaded with Content-Type: application/pdf (a lie)
    Then the upload is rejected, because we check the real file bytes,
    not the browser-supplied header
    """
    fake = io.BytesIO(b"just plain text, not a real PDF at all")
    r = client.post(
        "/api/seekers/70/resume",
        files={"file": ("resume.pdf", fake, "application/pdf")},
    )
    assert r.status_code == 400


def test_upload_accepts_real_docx_content(client):
    """
    Given a file with genuine DOCX magic bytes (a zip file signature)
    When uploaded with a .docx filename
    Then it's accepted, because DOCX files are zip archives under the hood
    """
    # Minimal valid zip file signature — enough to pass the magic-byte check.
    fake_docx = io.BytesIO(b"PK\x03\x04" + b"0" * 50)
    r = client.post(
        "/api/seekers/71/resume",
        files={"file": ("resume.docx", fake_docx,
                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert r.status_code == 201


def test_upload_path_traversal_filename_is_neutralized(client):
    """
    Security: a malicious filename must never affect where the file is saved

    Given a filename containing path traversal characters
    When a valid PDF is uploaded with that filename
    Then the upload still succeeds (content is valid), and the DISPLAYED
    filename has been stripped of any directory components
    """
    real_pdf = io.BytesIO(b"%PDF-1.4 fake but valid-looking pdf content")
    r = client.post(
        "/api/seekers/72/resume",
        files={"file": ("resume.pdf/../../../../etc/passwd", real_pdf, "application/pdf")},
    )
    assert r.status_code == 201
    filename = r.json()["resume_filename"]
    assert ".." not in filename
    assert "/" not in filename


# ---------------------------------------------------------------------------
# Security: input validation (length limits, email format)
# ---------------------------------------------------------------------------


def test_profile_info_rejects_invalid_email(client):
    """
    Given a seeker submits something that isn't a real email address
    When I PUT /api/seekers/{id} with that value in the email field
    Then the request is rejected with a validation error, not silently saved
    """
    r = client.put("/api/seekers/73", json={"email": "not an email at all"})
    assert r.status_code == 422


def test_profile_info_accepts_empty_email(client):
    """
    Given email is optional (no login system yet)
    When I PUT /api/seekers/{id} with an empty email string
    Then it's accepted (empty is valid; only non-empty-but-malformed is rejected)
    """
    r = client.put("/api/seekers/74", json={"email": ""})
    assert r.status_code == 200


def test_experience_description_length_is_capped(client):
    """
    Given someone submits a work experience description longer than the cap
    When I POST /api/seekers/{id}/experience
    Then the request is rejected rather than silently truncated or stored in full
    """
    r = client.post(
        "/api/seekers/75/experience",
        json={
            "job_title": "Dev",
            "company_name": "Co",
            "description": "x" * 5000,  # over the 2000-char cap
        },
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Resume parsing (NLP-lite auto-fill suggestions)
# ---------------------------------------------------------------------------


def test_parse_resume_not_found_when_none_uploaded(client):
    """
    Given a seeker who has never uploaded a resume
    When I GET /api/seekers/{id}/resume/parse
    Then I get 404, not a crash or empty-but-200 response
    """
    r = client.get("/api/seekers/999/resume/parse")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Resume parsing: work experience and education extraction
# ---------------------------------------------------------------------------


def _make_pdf_bytes(lines: list[str]) -> bytes:
    """Helper: build a minimal real PDF (via reportlab) from lines of text,
    so parsing tests exercise the actual PDF text-extraction path."""
    import io as _io
    from reportlab.pdfgen import canvas as _canvas

    buf = _io.BytesIO()
    c = _canvas.Canvas(buf)
    y = 800
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


def test_parse_extracts_multiple_experience_entries(client):
    """
    Given a resume with two work experience entries, each with a job title,
    company, date range on its own line, and a description
    When I scan the resume
    Then both entries are extracted with correct titles, companies, and dates
    """
    pdf_bytes = _make_pdf_bytes([
        "Test Person", "test@example.com",
        "EXPERIENCE",
        "Junior Developer, TechCo",
        "Jan 2023 - Present",
        "Built internal tools.",
        "Software Engineering Intern, StartupX",
        "Jun 2022 - Dec 2022",
        "Assisted with testing.",
        "EDUCATION",
        "Test University",
        "Bachelor of Science in Computer Science",
        "2019 - 2023",
    ])
    client.post("/api/seekers/80/resume", files={"file": ("resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")})

    r = client.get("/api/seekers/80/resume/parse")
    assert r.status_code == 200
    body = r.json()

    assert len(body["experience"]) == 2
    assert body["experience"][0]["job_title"] == "Junior Developer"
    assert body["experience"][0]["company_name"] == "TechCo"
    assert body["experience"][0]["start_date"] == "Jan 2023"
    assert body["experience"][0]["end_date"] == ""  # "Present" normalizes to blank
    assert body["experience"][1]["company_name"] == "StartupX"


def test_parse_extracts_education_entry(client):
    """
    Given a resume with an education section
    When I scan the resume
    Then institution, degree, field of study, and dates are extracted
    """
    pdf_bytes = _make_pdf_bytes([
        "Test Person", "test@example.com",
        "EDUCATION",
        "Test University",
        "Bachelor of Science in Computer Science",
        "2019 - 2023",
    ])
    client.post("/api/seekers/81/resume", files={"file": ("resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")})

    r = client.get("/api/seekers/81/resume/parse")
    body = r.json()
    assert len(body["education"]) == 1
    assert body["education"][0]["institution"] == "Test University"
    assert body["education"][0]["degree"] == "Bachelor"
    assert body["education"][0]["field_of_study"] == "Computer Science"


def test_parse_resume_with_no_experience_section_returns_empty_list(client):
    """
    Given a resume with no EXPERIENCE section at all
    When I scan the resume
    Then experience is an empty list, not an error
    """
    pdf_bytes = _make_pdf_bytes(["Test Person", "test@example.com", "SKILLS", "Python, SQL"])
    client.post("/api/seekers/82/resume", files={"file": ("resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")})

    r = client.get("/api/seekers/82/resume/parse")
    assert r.status_code == 200
    assert r.json()["experience"] == []
