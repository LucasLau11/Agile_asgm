import io

from job_portal.models import Job


def _login_new_seeker(client, tag, full_name="Test Seeker"):
    """Registers and logs in a fresh seeker account for test isolation —
    replaces the old pattern of just using an arbitrary numeric seeker_id
    in the URL, since real endpoints now require a real session. `tag`
    only needs to be unique per test (it becomes part of the email)."""
    client.post("/api/auth/register/seeker", json={
        "full_name": full_name,
        "email": f"seeker-{tag}@gmail.com",
        "password": "correcthorse",
    })


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


def test_get_job_shows_match_data_when_logged_in(client, sample_job):
    """
    Given a logged-in seeker with matching skills
    When I GET /api/jobs/{id}
    Then match_percentage and missing_skills reflect their real profile,
    sourced from the session — no seeker_id query param needed or accepted.
    """
    _login_new_seeker(client, "82")
    client.put("/api/seekers/me/skills", json={"skills": ["Python", "SQL"]})
    r = client.get(f"/api/jobs/{sample_job.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["match_percentage"] == 67
    assert body["missing_skills"] == ["FastAPI"]


def test_get_missing_job_returns_404(client):
    """
    US-21: View detailed job description (missing job)

    Given no job with ID 999 exists
    When I GET /api/jobs/999
    Then I receive 404 Not Found
    """
    r = client.get("/api/jobs/999")
    assert r.status_code == 404


def test_update_skills_creates_profile_on_first_use(client):
    """
    US-22: Maintain skill profile (first-time use)

    Given a newly-registered seeker who has never touched their profile
    When I PUT /api/seekers/me/skills with a skill list
    Then the profile (created at registration) has the skills saved
    """
    _login_new_seeker(client, "42")
    r = client.put("/api/seekers/me/skills", json={"skills": ["Python", "SQL"]})
    assert r.status_code == 200
    assert set(r.json()["skills"]) == {"Python", "SQL"}


def test_update_skills_replaces_existing_list(client):
    """
    US-22: Maintain skill profile (update)

    Given a seeker already has skills saved
    When I PUT a new skill list
    Then the old list is fully replaced, not merged
    """
    _login_new_seeker(client, "7")
    client.put("/api/seekers/me/skills", json={"skills": ["Python"]})
    r = client.put("/api/seekers/me/skills", json={"skills": ["React", "CSS"]})
    assert r.status_code == 200
    assert set(r.json()["skills"]) == {"React", "CSS"}


def test_update_skills_strips_blank_entries(client):
    """
    US-22: Maintain skill profile (input cleanup)

    Given the frontend sends a skill list with blank/whitespace entries
    When I PUT /api/seekers/me/skills
    Then blank entries are dropped rather than stored
    """
    _login_new_seeker(client, "8")
    r = client.put("/api/seekers/me/skills", json={"skills": ["Python", "  ", ""]})
    assert r.status_code == 200
    assert r.json()["skills"] == ["Python"]


def test_upload_resume_pdf_succeeds(client, tmp_path):
    """
    US-03: Upload resume

    Given a logged-in seeker has a valid PDF file
    When they POST it to /api/seekers/me/resume
    Then it's accepted and the filename is recorded on their profile
    """
    _login_new_seeker(client, "5")
    fake_pdf = io.BytesIO(b"%PDF-1.4 fake content for testing")
    r = client.post(
        "/api/seekers/me/resume",
        files={"file": ("resume.pdf", fake_pdf, "application/pdf")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["resume_filename"] == "resume.pdf"
    assert body["resume_url"] is not None


def test_upload_resume_rejects_wrong_file_type(client):
    """
    US-03: Upload resume (validation)

    Given a logged-in seeker tries to upload a .jpg file
    When they POST it to /api/seekers/me/resume
    Then they receive 400 Bad Request, and no profile change happens
    """
    _login_new_seeker(client, "5b")
    fake_image = io.BytesIO(b"not a real jpg but wrong content-type is what matters here")
    r = client.post(
        "/api/seekers/me/resume",
        files={"file": ("photo.jpg", fake_image, "image/jpeg")},
    )
    assert r.status_code == 400


def test_upload_resume_rejects_oversized_file(client):
    """
    US-03: Upload resume (size limit)

    Given a logged-in seeker tries to upload a PDF larger than 5 MB
    When they POST it to /api/seekers/me/resume
    Then they receive 400 Bad Request
    """
    _login_new_seeker(client, "5c")
    oversized = io.BytesIO(b"0" * (5 * 1024 * 1024 + 1))
    r = client.post(
        "/api/seekers/me/resume",
        files={"file": ("big_resume.pdf", oversized, "application/pdf")},
    )
    assert r.status_code == 400


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


def test_filter_by_salary_min_includes_jobs_at_or_above(client, db_session):
    """
    US-14: Filter jobs by salary range

    A max-salary filter was considered and deliberately dropped: filtering
    OUT higher-paying jobs works against the seeker's interest in the
    common case, so only a minimum floor is offered.

    Given a job paying RM4000+
    When I search for salary_min=3000
    Then the job shows up, since its minimum meets the floor I asked for
    """
    db_session.add(
        Job(employer_id=1, title="Well-paid job", description="x" * 60,
            salary_min=4000, salary_max=6000, status="open")
    )
    db_session.commit()

    r = client.get("/api/jobs?salary_min=3000")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_filter_by_salary_min_excludes_jobs_below(client, db_session):
    """
    Given a job paying RM1500-2200 (an internship stipend)
    When I search for salary_min=3000
    Then the job is excluded — its minimum falls below what I asked for
    """
    db_session.add(
        Job(employer_id=1, title="Low paying job", description="x" * 60,
            salary_min=1500, salary_max=2200, status="open")
    )
    db_session.commit()

    r = client.get("/api/jobs?salary_min=3000")
    assert r.status_code == 200
    assert r.json() == []


def test_filter_by_salary_min_excludes_unspecified_salary(client, db_session):
    """
    Given a job with no salary specified at all
    When I apply a salary_min filter
    Then that job is excluded — its salary can't be verified to meet the
    filter, so it's not assumed to pass
    """
    db_session.add(
        Job(employer_id=1, title="No salary listed", description="x" * 60,
            salary_min=None, salary_max=None, status="open")
    )
    db_session.commit()

    r = client.get("/api/jobs?salary_min=3000")
    assert r.status_code == 200
    assert r.json() == []


def test_no_salary_filter_still_shows_unspecified_salary_jobs(client, db_session):
    """
    Given a job with no salary specified
    When I browse WITHOUT any salary filter applied
    Then the job still shows up — only an active filter excludes it
    """
    db_session.add(
        Job(employer_id=1, title="No salary listed", description="x" * 60,
            salary_min=None, salary_max=None, status="open")
    )
    db_session.commit()

    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert len(r.json()) == 1

# ---------------------------------------------------------------------------
# Match data + sorting on the main job list (UX addition: don't make a
# seeker click into every job just to see how well they match it)
# ---------------------------------------------------------------------------


def test_list_jobs_without_seeker_id_has_no_match_data(client, sample_job):
    r = client.get("/api/jobs")
    assert r.status_code == 200
    body = r.json()[0]
    assert body["match_percentage"] is None
    assert body["missing_skills"] == []


def test_list_jobs_shows_match_data_when_logged_in(client, sample_job):
    _login_new_seeker(client, "80")
    client.put("/api/seekers/me/skills", json={"skills": ["Python", "SQL"]})
    r = client.get("/api/jobs")
    assert r.status_code == 200
    body = r.json()[0]
    assert body["match_percentage"] == 67
    assert body["missing_skills"] == ["FastAPI"]


def test_sort_by_match_orders_best_match_first(client, db_session):
    db_session.add_all([
        Job(employer_id=1, title="Low match job", description="x" * 60,
            skills_required="Python,Java,C++,Go", status="open"),
        Job(employer_id=1, title="High match job", description="x" * 60,
            skills_required="Python", status="open"),
    ])
    db_session.commit()
    _login_new_seeker(client, "81")
    client.put("/api/seekers/me/skills", json={"skills": ["Python"]})
    r = client.get("/api/jobs?sort_by=match")
    assert r.status_code == 200
    titles = [job["title"] for job in r.json()]
    assert titles[0] == "High match job"


def test_sort_by_match_without_seeker_id_falls_back_to_newest(client, db_session):
    r = client.get("/api/jobs?sort_by=match")
    assert r.status_code == 200


def test_sort_by_salary_high_orders_highest_first(client, db_session):
    db_session.add_all([
        Job(employer_id=1, title="Lower paying", description="x" * 60,
            salary_min=2000, salary_max=3000, status="open"),
        Job(employer_id=1, title="Higher paying", description="x" * 60,
            salary_min=6000, salary_max=8000, status="open"),
    ])
    db_session.commit()
    r = client.get("/api/jobs?sort_by=salary_high")
    assert r.status_code == 200
    titles = [job["title"] for job in r.json()]
    assert titles[0] == "Higher paying"


def test_sort_by_salary_low_orders_lowest_first(client, db_session):
    db_session.add_all([
        Job(employer_id=1, title="Lower paying", description="x" * 60,
            salary_min=2000, salary_max=3000, status="open"),
        Job(employer_id=1, title="Higher paying", description="x" * 60,
            salary_min=6000, salary_max=8000, status="open"),
    ])
    db_session.commit()
    r = client.get("/api/jobs?sort_by=salary_low")
    assert r.status_code == 200
    titles = [job["title"] for job in r.json()]
    assert titles[0] == "Lower paying"


def test_credibility_reasons_flag_missing_salary(client, db_session):
    db_session.add(
        Job(employer_id=1, title="No salary job", description="x" * 60,
            skills_required="Python", location="KL",
            salary_min=None, salary_max=None, status="open")
    )
    db_session.commit()
    r = client.get("/api/jobs")
    reasons = r.json()[0]["credibility_reasons"]
    assert "Salary not specified" in reasons


def test_credibility_reasons_empty_for_a_fully_complete_posting(client, db_session):
    employer_id = 42
    for i in range(5):
        db_session.add(
            Job(employer_id=employer_id, title=f"Prior job {i}", description="x" * 60,
                skills_required="Python", location="KL", salary_min=3000, salary_max=5000,
                positions_available=1, status="closed")
        )
    db_session.add(
        Job(employer_id=employer_id, title="Complete job", description="x" * 60,
            skills_required="Python", location="KL", salary_min=3000, salary_max=5000,
            positions_available=1, status="open")
    )
    db_session.commit()
    r = client.get("/api/jobs")
    complete_job = next(j for j in r.json() if j["title"] == "Complete job")
    assert complete_job["credibility_reasons"] == []

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


def test_recommended_jobs_scores_by_skill_overlap(client, db_session):
    """
    Given a logged-in seeker with skills Python, SQL
    And a job requiring Python, SQL, Docker
    When I fetch my recommended jobs
    Then the job is returned with a 67% match (2 of 3 required skills)
    """
    _login_new_seeker(client, "50")
    client.put("/api/seekers/me/skills", json={"skills": ["Python", "SQL"]})
    db_session.add(
        Job(employer_id=1, title="Matched job", description="x" * 60,
            skills_required="Python,SQL,Docker", status="open")
    )
    db_session.commit()

    r = client.get("/api/jobs/recommended")
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    assert results[0]["match_percentage"] == 67


def test_recommended_jobs_excludes_zero_overlap(client, db_session):
    """
    Given a logged-in seeker with skills that share nothing with a job's requirements
    When I fetch my recommended jobs
    Then that job is excluded entirely (0% match doesn't clear the min_match bar)
    """
    _login_new_seeker(client, "51")
    client.put("/api/seekers/me/skills", json={"skills": ["Photoshop"]})
    db_session.add(
        Job(employer_id=1, title="Unrelated job", description="x" * 60,
            skills_required="Python,SQL", status="open")
    )
    db_session.commit()

    r = client.get("/api/jobs/recommended")
    assert r.json() == []


def test_recommended_jobs_requires_login(client):
    """
    Given nobody is logged in
    When I GET /api/jobs/recommended
    Then I get 401 — recommendations require a real account now that
    browsing personalization no longer depends on a client-supplied id.
    """
    r = client.get("/api/jobs/recommended")
    assert r.status_code == 401


def test_recommended_jobs_empty_when_seeker_has_no_skills(client):
    """
    Given a logged-in seeker who has never set any skills
    When I fetch recommended jobs
    Then I get an empty list rather than an error
    """
    _login_new_seeker(client, "52")
    r = client.get("/api/jobs/recommended")
    assert r.status_code == 200
    assert r.json() == []


def test_update_profile_info(client):
    """
    Given a logged-in seeker fills in their personal details
    When I PUT /api/seekers/me with name/email/phone/bio
    Then the profile reflects those values
    """
    _login_new_seeker(client, "60")
    r = client.put(
        "/api/seekers/me",
        json={"full_name": "Jane Doe", "email": "jane-profile-update@gmail.com", "phone": "012-3456789", "bio": "Hello."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "Jane Doe"
    assert body["email"] == "jane-profile-update@gmail.com"


def test_add_and_delete_experience(client):
    """
    Given a logged-in seeker adds a work experience entry
    When I POST then DELETE it
    Then it appears after adding and disappears after deleting
    """
    _login_new_seeker(client, "61")
    r = client.post(
        "/api/seekers/me/experience",
        json={"job_title": "Intern", "company_name": "TechCo", "start_date": "2023", "end_date": "2024",
              "description": "Did things."},
    )
    assert r.status_code == 201
    body = r.json()
    assert len(body["experience"]) == 1
    exp_id = body["experience"][0]["id"]

    r2 = client.delete(f"/api/seekers/me/experience/{exp_id}")
    assert r2.status_code == 200
    assert r2.json()["experience"] == []


def test_delete_experience_not_found_returns_404(client):
    """
    Given no experience entry with ID 999 exists for this seeker
    When I try to delete it
    Then I get 404, not a silent success
    """
    _login_new_seeker(client, "62")
    r = client.delete("/api/seekers/me/experience/999")
    assert r.status_code == 404


def test_add_and_delete_education(client):
    """
    Given a logged-in seeker adds an education entry
    When I POST then DELETE it
    Then it appears after adding and disappears after deleting
    """
    _login_new_seeker(client, "63")
    r = client.post(
        "/api/seekers/me/education",
        json={"institution": "USM", "degree": "Bachelor's Degree", "field_of_study": "Computer Science",
              "start_date": "2019", "end_date": "2023"},
    )
    assert r.status_code == 201
    edu_id = r.json()["education"][0]["id"]

    r2 = client.delete(f"/api/seekers/me/education/{edu_id}")
    assert r2.status_code == 200
    assert r2.json()["education"] == []


def test_upload_rejects_spoofed_content_type(client):
    """
    Security: a file with a fake Content-Type header but non-PDF actual
    content must be rejected

    Given a plain text file
    When it's uploaded with Content-Type: application/pdf (a lie)
    Then the upload is rejected, because we check the real file bytes,
    not the browser-supplied header
    """
    _login_new_seeker(client, "70")
    fake = io.BytesIO(b"just plain text, not a real PDF at all")
    r = client.post(
        "/api/seekers/me/resume",
        files={"file": ("resume.pdf", fake, "application/pdf")},
    )
    assert r.status_code == 400


def test_upload_accepts_real_docx_content(client):
    """
    Given a file with genuine DOCX magic bytes (a zip file signature)
    When uploaded with a .docx filename
    Then it's accepted, because DOCX files are zip archives under the hood
    """
    _login_new_seeker(client, "71")
    # Minimal valid zip file signature — enough to pass the magic-byte check.
    fake_docx = io.BytesIO(b"PK\x03\x04" + b"0" * 50)
    r = client.post(
        "/api/seekers/me/resume",
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
    _login_new_seeker(client, "72")
    real_pdf = io.BytesIO(b"%PDF-1.4 fake but valid-looking pdf content")
    r = client.post(
        "/api/seekers/me/resume",
        files={"file": ("resume.pdf/../../../../etc/passwd", real_pdf, "application/pdf")},
    )
    assert r.status_code == 201
    filename = r.json()["resume_filename"]
    assert ".." not in filename
    assert "/" not in filename


def test_profile_info_rejects_invalid_email(client):
    """
    Given a logged-in seeker submits something that isn't a real email address
    When I PUT /api/seekers/me with that value in the email field
    Then the request is rejected with a validation error, not silently saved
    """
    _login_new_seeker(client, "73")
    r = client.put("/api/seekers/me", json={"email": "not an email at all"})
    assert r.status_code == 422


def test_profile_info_rejects_empty_email(client):
    """
    Given name/email/phone are all required on the profile form
    When I PUT /api/seekers/me with an empty email string
    Then it's rejected rather than silently saved
    """
    _login_new_seeker(client, "74")
    r = client.put(
        "/api/seekers/me",
        json={"full_name": "Jane Doe", "email": "", "phone": "012-3456789"},
    )
    assert r.status_code == 422


def test_profile_info_rejects_name_with_digits(client):
    """
    Given a name field must not contain numbers
    When I PUT /api/seekers/me with a digit in full_name
    Then the request is rejected
    """
    _login_new_seeker(client, "76")
    r = client.put(
        "/api/seekers/me",
        json={"full_name": "Jane2 Doe", "email": "jane76@gmail.com", "phone": "012-3456789"},
    )
    assert r.status_code == 422


def test_profile_info_rejects_phone_with_letters(client):
    """
    Given a phone field must only contain digits/phone punctuation
    When I PUT /api/seekers/me with letters in the phone field
    Then the request is rejected
    """
    _login_new_seeker(client, "77")
    r = client.put(
        "/api/seekers/me",
        json={"full_name": "Jane Doe", "email": "jane77@gmail.com", "phone": "012-EXAMPLE"},
    )
    assert r.status_code == 422


def test_experience_description_length_is_capped(client):
    """
    Given someone submits a work experience description longer than the cap
    When I POST /api/seekers/me/experience
    Then the request is rejected rather than silently truncated or stored in full
    """
    _login_new_seeker(client, "75")
    r = client.post(
        "/api/seekers/me/experience",
        json={
            "job_title": "Dev",
            "company_name": "Co",
            "description": "x" * 5000,  # over the 2000-char cap
        },
    )
    assert r.status_code == 422


def test_parse_resume_not_found_when_none_uploaded(client):
    """
    Given a logged-in seeker who has never uploaded a resume
    When I GET /api/seekers/me/resume/parse
    Then I get 404, not a crash or empty-but-200 response
    """
    _login_new_seeker(client, "999")
    r = client.get("/api/seekers/me/resume/parse")
    assert r.status_code == 404


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
    _login_new_seeker(client, "80")
    pdf_bytes = _make_pdf_bytes([
        "Test Person", "test@gmail.com",
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
    client.post("/api/seekers/me/resume", files={"file": ("resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")})

    r = client.get("/api/seekers/me/resume/parse")
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
    _login_new_seeker(client, "81b")
    pdf_bytes = _make_pdf_bytes([
        "Test Person", "test@gmail.com",
        "EDUCATION",
        "Test University",
        "Bachelor of Science in Computer Science",
        "2019 - 2023",
    ])
    client.post("/api/seekers/me/resume", files={"file": ("resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")})

    r = client.get("/api/seekers/me/resume/parse")
    body = r.json()
    assert len(body["education"]) == 1
    assert body["education"][0]["institution"] == "Test University"
    assert body["education"][0]["degree"] == "Bachelor's Degree"
    assert body["education"][0]["field_of_study"] == "Computer Science"


def test_parse_resume_with_no_experience_section_returns_empty_list(client):
    """
    Given a resume with no EXPERIENCE section at all
    When I scan the resume
    Then experience is an empty list, not an error
    """
    _login_new_seeker(client, "82")
    pdf_bytes = _make_pdf_bytes(["Test Person", "test@gmail.com", "SKILLS", "Python, SQL"])
    client.post("/api/seekers/me/resume", files={"file": ("resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")})

    r = client.get("/api/seekers/me/resume/parse")
    assert r.status_code == 200
    assert r.json()["experience"] == []


def test_seeker_endpoint_requires_login(client):
    """
    Given nobody is logged in
    When I try to fetch "my" profile
    Then I get 401, not a crash or someone else's data
    """
    r = client.get("/api/seekers/me")
    assert r.status_code == 401


def test_seeker_endpoint_rejects_employer_session(client):
    """
    Given someone is logged in as an EMPLOYER, not a seeker
    When they try to fetch "my" seeker profile
    Then they get 401 — the seeker-only endpoints aren't for them
    """
    client.post("/api/auth/register/employer", json={
        "company_name": "Some Co", "email": "not-a-seeker@gmail.com", "password": "correcthorse",
    })
    r = client.get("/api/seekers/me")
    assert r.status_code == 401


def test_seeker_can_only_see_own_profile_data(client):
    """
    Given two different registered seekers, each with their own experience entry
    When seeker B fetches "my" profile
    Then they see only their own data, never seeker A's
    """
    _login_new_seeker(client, "ownerA", full_name="Seeker A")
    client.post("/api/seekers/me/experience", json={
        "job_title": "A's job", "company_name": "A Co",
    })
    client.post("/api/auth/logout")

    _login_new_seeker(client, "ownerB", full_name="Seeker B")
    r = client.get("/api/seekers/me")
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "Seeker B"
    assert body["experience"] == []


def test_applications_fragment_requires_login(client):
    """
    Given nobody is logged in
    When I GET /my-applications-fragment
    Then I get 401, not a page rendered for the wrong/no user
    """
    r = client.get("/my-applications-fragment")
    assert r.status_code == 401


def test_applications_fragment_works_for_logged_in_seeker(client):
    """
    Given a logged-in seeker with no applications yet
    When I GET /my-applications-fragment
    Then I get a 200 with the empty-state message, not an error
    """
    _login_new_seeker(client, "fragtest")
    r = client.get("/my-applications-fragment")
    assert r.status_code == 200
    assert "haven't submitted any job applications" in r.text


def test_cannot_delete_another_seekers_experience(client):
    """
    Given seeker A has a real work experience entry
    When seeker B (a different logged-in account) tries to delete it by its real id
    Then it 404s — B's session can't reach A's data no matter what id they guess,
    and A's entry is still there afterward
    """
    _login_new_seeker(client, "delOwnerA", full_name="Delete Owner A")
    add_res = client.post("/api/seekers/me/experience", json={
        "job_title": "A's job", "company_name": "A Co",
    })
    exp_id = add_res.json()["experience"][0]["id"]
    client.post("/api/auth/logout")

    _login_new_seeker(client, "delOwnerB", full_name="Delete Owner B")
    r = client.delete(f"/api/seekers/me/experience/{exp_id}")
    assert r.status_code == 404
    client.post("/api/auth/logout")

    # Log back into A's own account (not a new registration) and confirm
    # the entry is still there, untouched by B's attempt.
    login_res = client.post("/api/auth/login", json={
        "email": "seeker-delOwnerA@gmail.com", "password": "correcthorse",
    })
    assert login_res.status_code == 200
    me = client.get("/api/seekers/me")
    assert len(me.json()["experience"]) == 1
    assert me.json()["experience"][0]["id"] == exp_id


def test_cannot_delete_another_seekers_education(client):
    """
    Given seeker A has a real education entry
    When seeker B tries to delete it by its real id
    Then it 404s, same as the experience case above
    """
    _login_new_seeker(client, "eduOwnerA", full_name="Edu Owner A")
    add_res = client.post("/api/seekers/me/education", json={
        "institution": "A University",
    })
    edu_id = add_res.json()["education"][0]["id"]
    client.post("/api/auth/logout")

    _login_new_seeker(client, "eduOwnerB", full_name="Edu Owner B")
    r = client.delete(f"/api/seekers/me/education/{edu_id}")
    assert r.status_code == 404


def test_applications_fragment_rejects_employer_session(client):
    """
    Given someone is logged in as an employer, not a seeker
    When they GET /my-applications-fragment
    Then they get 401 — same role check as every other seeker-only endpoint
    """
    client.post("/api/auth/register/employer", json={
        "company_name": "Some Co", "email": "not-a-seeker-frag@gmail.com", "password": "correcthorse",
    })
    r = client.get("/my-applications-fragment")
    assert r.status_code == 401


def test_update_profile_rejects_email_already_used_by_another_account(client):
    """
    Given seeker A is registered with a real email
    When seeker B tries to change THEIR OWN profile email to A's email
    Then it's rejected with 409 — B can't hijack A's login identifier
    """
    _login_new_seeker(client, "emailOwnerA", full_name="Email Owner A")
    client.post("/api/auth/logout")

    _login_new_seeker(client, "emailOwnerB", full_name="Email Owner B")
    r = client.put("/api/seekers/me", json={
        "full_name": "Email Owner B",
        "email": "seeker-emailOwnerA@gmail.com",
        "phone": "012-3456789",
    })
    assert r.status_code == 409


def test_update_profile_allows_keeping_same_email(client):
    """
    Given a seeker updates their profile WITHOUT changing their email
    When I PUT /api/seekers/me with the same email they already have
    Then it succeeds — the uniqueness check only blocks a change to
    SOMEONE ELSE'S email, not "no-op" resubmission of your own
    """
    _login_new_seeker(client, "sameEmail", full_name="Same Email Seeker")
    r = client.put("/api/seekers/me", json={
        "full_name": "Same Email Seeker Updated",
        "email": "seeker-sameEmail@gmail.com",
        "phone": "012-3456789",
    })
    assert r.status_code == 200
    assert r.json()["full_name"] == "Same Email Seeker Updated"


def test_apply_page_requires_login(client, sample_job):
    r = client.get(f"/apply?job_id={sample_job.id}", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/UI/html/login.html"


def test_apply_page_loads_for_logged_in_seeker(client, sample_job):
    _login_new_seeker(client, "applyPage")
    r = client.get(f"/apply?job_id={sample_job.id}")
    assert r.status_code == 200
    assert sample_job.title in r.text


def test_apply_page_rejects_employer_session(client, sample_job):
    client.post("/api/auth/register/employer", json={
        "company_name": "Some Co", "email": "not-a-seeker-apply@gmail.com", "password": "correcthorse",
    })
    r = client.get(f"/apply?job_id={sample_job.id}", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/UI/html/login.html"


def test_submitting_application_requires_login(client, sample_job):
    r = client.post("/apply", data={"job_id": sample_job.id, "cover_letter": "Hire me"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/UI/html/login.html"


def test_submitting_application_uses_session_seeker_id(client, sample_job):
    """
    Given a logged-in seeker submits an application
    When I POST /apply (there's no seeker_id field in the form at all
    anymore — the backend only ever trusts the session)
    Then the application is stamped with THAT seeker's real id, and shows
    up when they fetch their own applications afterward.
    """
    _login_new_seeker(client, "applySubmit", full_name="Apply Submitter")

    r = client.post("/apply", data={"job_id": sample_job.id, "cover_letter": "Hire me"})
    assert r.status_code in (200, 303)

    apps = client.get("/api/applications").json()
    assert len(apps) == 1
    assert apps[0]["job_title"] == sample_job.title


def test_cannot_submit_application_as_someone_else(client, sample_job):
    """
    Given seeker A submitted an application while logged in
    When a different seeker B logs in and fetches THEIR OWN applications
    Then B sees an empty list — A's application isn't visible to B, and
    there's no client-controlled identity field left on the form to spoof.
    """
    _login_new_seeker(client, "applySpoofA", full_name="Real Applicant")
    client.post("/apply", data={"job_id": sample_job.id, "cover_letter": "Hire me"})
    client.post("/api/auth/logout")

    _login_new_seeker(client, "applySpoofB", full_name="Other Seeker")
    apps = client.get("/api/applications").json()
    assert apps == []


def test_api_applications_requires_login(client):
    r = client.get("/api/applications")
    assert r.status_code == 401


def test_application_submitted_while_logged_in_appears_in_own_tracker(client, sample_job):
    """
    Closes the phase 2a interim gap: an application submitted through the
    real apply flow while logged in must show up in that same seeker's own
    tracker — both the JSON endpoint (my_application.html) and the HTML
    fragment (profile.html's applications tracker).
    """
    _login_new_seeker(client, "e2eApply", full_name="End to End Applicant")

    r = client.post("/apply", data={"job_id": sample_job.id, "cover_letter": "I would love to work here."})
    assert r.status_code in (200, 303)

    api_apps = client.get("/api/applications").json()
    assert len(api_apps) == 1
    assert api_apps[0]["job_title"] == sample_job.title

    fragment = client.get("/my-applications-fragment")
    assert fragment.status_code == 200
    assert sample_job.title in fragment.text
    assert "haven't submitted any job applications" not in fragment.text
