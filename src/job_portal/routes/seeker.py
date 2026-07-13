"""
Teammate B's routes: job discovery + seeker profile.

Covers:
  US-03  Upload resume
  US-12  Search jobs by keyword
  US-13  Filter jobs by location
  US-20  View job postings
  US-21  View job details
  US-22  Maintain skill profile

Sprint 1 extension: advanced filters (state, salary, job type), positions
remaining display, resume/skill-based job recommendations, and a fuller
seeker profile (personal info + work experience + education).
"""

import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from job_portal.database import get_db
from job_portal.models import Education, Job, SeekerProfile, WorkExperience
from job_portal.schemas import (
    EducationIn,
    EducationOut,
    ExperienceIn,
    ExperienceOut,
    JobOut,
    ParsedResumeOut,
    ProfileInfoUpdate,
    SeekerProfileOut,
    SkillsUpdate,
)
from job_portal.services.file_validation import (
    ALLOWED_EXTENSIONS,
    MAX_RESUME_SIZE_BYTES,
    detect_safe_extension,
    sanitize_display_filename,
)
from job_portal.services.resume_parser import parse_resume

router = APIRouter(tags=["seeker"])

# Where uploaded resumes get stored for Sprint 1 (local disk).
# In a later sprint this can be swapped for Supabase Storage without
# changing the route logic below — only this constant + the save step.
RESUME_UPLOAD_DIR = os.getenv("RESUME_UPLOAD_DIR", "uploads/resumes")


def _get_or_create_profile(db: Session, seeker_id: int) -> SeekerProfile:
    """Helper: fetch a seeker's profile, creating an empty one if it doesn't exist yet.

    This matters because there's no registration flow yet (Sprint 3) — so the
    first time a seeker touches their profile, we create the row on the fly.
    """
    profile = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == seeker_id).first()
    if profile is None:
        profile = SeekerProfile(seeker_id=seeker_id, skills="")
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# US-20 / US-12 / US-13 — Browse, search, and filter job postings
# (extended with state / salary / job_type filters)
# ---------------------------------------------------------------------------


@router.get("/api/jobs", response_model=List[JobOut])
def list_jobs(
    keyword: Optional[str] = None,
    location: Optional[str] = None,
    state: Optional[str] = None,
    job_type: Optional[str] = None,
    salary_min: Optional[int] = None,
    salary_max: Optional[int] = None,
    db: Session = Depends(get_db),
) -> List[JobOut]:
    """
    List job postings, optionally filtered. All filters combine with AND logic.

    - No params  -> US-20: view all open job postings.
    - `keyword`   -> US-12: matches against title OR description (case-insensitive).
    - `location`  -> US-13: matches against location (case-insensitive, partial match).
    - `state`     -> advanced filter: exact match against the job's state/region.
    - `job_type`  -> advanced filter: exact match (Full-time / Part-time / Contract / Internship / Remote).
    - `salary_min`, `salary_max` -> advanced filter: keep jobs whose salary range
      OVERLAPS the requested range (not just contained within it), so e.g. a job
      paying RM4000-6000 still shows up if you search for RM5000-8000.
    """
    query = db.query(Job).filter(Job.status == "open")

    if keyword:
        like = f"%{keyword}%"
        query = query.filter((Job.title.ilike(like)) | (Job.description.ilike(like)))

    if location:
        query = query.filter(Job.location.ilike(f"%{location}%"))

    if state:
        query = query.filter(Job.state.ilike(state))

    if job_type:
        query = query.filter(Job.job_type.ilike(job_type))

    if salary_min is not None:
        # Exclude jobs whose max salary is below what the seeker wants.
        query = query.filter((Job.salary_max.is_(None)) | (Job.salary_max >= salary_min))

    if salary_max is not None:
        # Exclude jobs whose min salary is above what the seeker wants.
        query = query.filter((Job.salary_min.is_(None)) | (Job.salary_min <= salary_max))

    jobs = query.order_by(Job.created_at.desc()).all()
    return [JobOut.from_job(job, credibility_score=_placeholder_score(job)) for job in jobs]


# ---------------------------------------------------------------------------
# Resume/skill-based job matching (fulfils the "so the system can match me
# with suitable jobs" part of US-22)
#
# IMPORTANT: this route MUST be declared before `/api/jobs/{job_id}` below.
# FastAPI matches routes in declaration order, and "/api/jobs/recommended"
# would otherwise get swallowed by "/api/jobs/{job_id}" (with job_id literally
# set to the string "recommended", which then fails to parse as an int).
# ---------------------------------------------------------------------------


def _match_percentage(seeker_skills: list[str], job_skills: list[str]) -> int:
    """
    Simple overlap-based matching algorithm.

    Score = (number of the job's required skills that the seeker has)
             / (total number of the job's required skills) * 100

    This deliberately measures "how much of what THIS JOB wants do I have",
    not the other way around — a seeker with 20 skills shouldn't be penalised
    for a job that only lists 2 required skills. Jobs with no listed skills
    are treated as a weak/no match (they give recruiters no way to compare).

    Case-insensitive so "python" and "Python" count as the same skill.
    """
    if not job_skills:
        return 0
    seeker_set = {s.strip().lower() for s in seeker_skills if s.strip()}
    job_set = {s.strip().lower() for s in job_skills if s.strip()}
    if not seeker_set or not job_set:
        return 0
    overlap = seeker_set & job_set
    return round(len(overlap) / len(job_set) * 100)


@router.get("/api/jobs/recommended", response_model=List[JobOut])
def recommended_jobs(
    seeker_id: int,
    min_match: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
) -> List[JobOut]:
    """
    Recommend open jobs based on overlap between the seeker's saved skills
    and each job's required skills. Returns jobs sorted by match percentage
    (highest first), excluding jobs below `min_match`% (default: any match
    at all). Returns an empty list if the seeker has no skills saved yet —
    the frontend should hide the "Recommended for you" section in that case.
    """
    profile = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == seeker_id).first()
    seeker_skills = profile.skills_list() if profile else []
    if not seeker_skills:
        return []

    jobs = db.query(Job).filter(Job.status == "open").all()
    scored = []
    for job in jobs:
        pct = _match_percentage(seeker_skills, job.skills_list())
        if pct >= min_match:
            scored.append((pct, job))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        JobOut.from_job(job, credibility_score=_placeholder_score(job), match_percentage=pct)
        for pct, job in scored[:limit]
    ]


@router.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    """US-21: View full details of a single job posting."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut.from_job(job, credibility_score=_placeholder_score(job))


def _placeholder_score(job: Job) -> int:
    """
    Temporary stand-in for Teammate C's credibility score (US-11).

    Once C's `services/credibility.py` lands, replace this with:
        from job_portal.services.credibility import compute_credibility_score
        return compute_credibility_score(job)

    Kept here so Teammate B's endpoints return a complete, testable
    response shape without blocking on C's branch merging first.
    """
    score = 20
    if job.description and len(job.description) > 50:
        score += 20
    if job.location:
        score += 20
    if job.skills_list():
        score += 20
    return min(score, 100)


# ---------------------------------------------------------------------------
# US-22 — Maintain skill profile + personal info (profile upgrade)
# ---------------------------------------------------------------------------


@router.get("/api/seekers/{seeker_id}", response_model=SeekerProfileOut)
def get_seeker_profile(seeker_id: int, db: Session = Depends(get_db)) -> SeekerProfileOut:
    """Fetch a seeker's profile (creates an empty one if this is their first visit)."""
    profile = _get_or_create_profile(db, seeker_id)
    return SeekerProfileOut.from_profile(profile)


@router.put("/api/seekers/{seeker_id}", response_model=SeekerProfileOut)
def update_profile_info(
    seeker_id: int, payload: ProfileInfoUpdate, db: Session = Depends(get_db)
) -> SeekerProfileOut:
    """Update personal info (name, email, phone, bio) — the 'real profile' fields."""
    profile = _get_or_create_profile(db, seeker_id)
    profile.full_name = payload.full_name
    profile.email = payload.email
    profile.phone = payload.phone
    profile.bio = payload.bio
    db.commit()
    db.refresh(profile)
    return SeekerProfileOut.from_profile(profile)


@router.put("/api/seekers/{seeker_id}/skills", response_model=SeekerProfileOut)
def update_skills(
    seeker_id: int, payload: SkillsUpdate, db: Session = Depends(get_db)
) -> SeekerProfileOut:
    """US-22: Replace the seeker's skill list so job matching can use it."""
    profile = _get_or_create_profile(db, seeker_id)
    cleaned = [s.strip() for s in payload.skills if s.strip()]
    profile.skills = ",".join(cleaned)
    db.commit()
    db.refresh(profile)
    return SeekerProfileOut.from_profile(profile)


# ---------------------------------------------------------------------------
# Work experience (part of the "real profile" upgrade)
# ---------------------------------------------------------------------------


@router.post("/api/seekers/{seeker_id}/experience", response_model=SeekerProfileOut, status_code=201)
def add_experience(
    seeker_id: int, payload: ExperienceIn, db: Session = Depends(get_db)
) -> SeekerProfileOut:
    profile = _get_or_create_profile(db, seeker_id)
    entry = WorkExperience(seeker_profile_id=profile.id, **payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(profile)
    return SeekerProfileOut.from_profile(profile)


@router.delete("/api/seekers/{seeker_id}/experience/{experience_id}", response_model=SeekerProfileOut)
def delete_experience(
    seeker_id: int, experience_id: int, db: Session = Depends(get_db)
) -> SeekerProfileOut:
    profile = _get_or_create_profile(db, seeker_id)
    entry = (
        db.query(WorkExperience)
        .filter(WorkExperience.id == experience_id, WorkExperience.seeker_profile_id == profile.id)
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Experience entry not found")
    db.delete(entry)
    db.commit()
    db.refresh(profile)
    return SeekerProfileOut.from_profile(profile)


# ---------------------------------------------------------------------------
# Education (part of the "real profile" upgrade)
# ---------------------------------------------------------------------------


@router.post("/api/seekers/{seeker_id}/education", response_model=SeekerProfileOut, status_code=201)
def add_education(
    seeker_id: int, payload: EducationIn, db: Session = Depends(get_db)
) -> SeekerProfileOut:
    profile = _get_or_create_profile(db, seeker_id)
    entry = Education(seeker_profile_id=profile.id, **payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(profile)
    return SeekerProfileOut.from_profile(profile)


@router.delete("/api/seekers/{seeker_id}/education/{education_id}", response_model=SeekerProfileOut)
def delete_education(
    seeker_id: int, education_id: int, db: Session = Depends(get_db)
) -> SeekerProfileOut:
    profile = _get_or_create_profile(db, seeker_id)
    entry = (
        db.query(Education)
        .filter(Education.id == education_id, Education.seeker_profile_id == profile.id)
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Education entry not found")
    db.delete(entry)
    db.commit()
    db.refresh(profile)
    return SeekerProfileOut.from_profile(profile)


# ---------------------------------------------------------------------------
# US-03 — Upload resume
# ---------------------------------------------------------------------------


@router.post("/api/seekers/{seeker_id}/resume", response_model=SeekerProfileOut, status_code=201)
async def upload_resume(
    seeker_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> SeekerProfileOut:
    """
    US-03: Upload a resume file (PDF or Word doc, max 5 MB).

    SECURITY: we deliberately do NOT trust file.content_type (a browser-set
    header, trivially spoofable) or use file.filename to build the saved
    path (attacker-controlled — a path-traversal risk). Instead we sniff
    the file's actual magic bytes to confirm it's really a PDF/DOC/DOCX,
    and always generate the saved filename ourselves from a UUID. The
    original filename is kept ONLY for display, after being stripped of
    any path components.

    Sprint 1 stores the file on local disk under RESUME_UPLOAD_DIR and keeps
    the path in the DB. Swappable for Supabase Storage later without touching
    the calling code on the frontend.
    """
    contents = await file.read()

    if len(contents) > MAX_RESUME_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Resume must be under 5 MB.")

    safe_extension = detect_safe_extension(contents)
    if safe_extension is None:
        raise HTTPException(
            status_code=400,
            detail="Resume must be a genuine PDF or Word document (.pdf, .doc, .docx). "
            "The file's content didn't match any of those formats.",
        )

    os.makedirs(RESUME_UPLOAD_DIR, exist_ok=True)
    # Filename is built ENTIRELY server-side — seeker_id (int, safe) + a
    # random UUID + the extension WE detected from real content, never
    # anything derived from the client-supplied filename.
    stored_name = f"{seeker_id}_{uuid.uuid4().hex}{safe_extension}"
    stored_path = os.path.join(RESUME_UPLOAD_DIR, stored_name)

    with open(stored_path, "wb") as f:
        f.write(contents)

    profile = _get_or_create_profile(db, seeker_id)
    profile.resume_filename = sanitize_display_filename(file.filename)
    profile.resume_url = stored_path
    db.commit()
    db.refresh(profile)
    return SeekerProfileOut.from_profile(profile)


@router.get("/api/seekers/{seeker_id}/resume/parse", response_model=ParsedResumeOut)
def parse_seeker_resume(seeker_id: int, db: Session = Depends(get_db)) -> ParsedResumeOut:
    """
    Scan the seeker's already-uploaded resume and extract suggested profile
    data (name, email, phone, skills) using lightweight text extraction +
    pattern matching (see services/resume_parser.py for the full approach
    and its honest limitations).

    Returns suggestions ONLY — nothing here is written to the database.
    The frontend shows these to the user, who chooses what to actually
    apply via the existing profile/skills update endpoints.
    """
    profile = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == seeker_id).first()
    if profile is None or not profile.resume_url:
        raise HTTPException(status_code=404, detail="No resume uploaded yet for this seeker.")

    if not os.path.exists(profile.resume_url):
        raise HTTPException(status_code=404, detail="Resume file is missing from storage.")

    extension = os.path.splitext(profile.resume_url)[1]
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported resume format for scanning.")

    with open(profile.resume_url, "rb") as f:
        contents = f.read()

    result = parse_resume(contents, extension)
    return ParsedResumeOut(
        full_name=result.full_name,
        email=result.email,
        phone=result.phone,
        bio=result.bio,
        skills=result.skills,
        experience=result.experience,
        education=result.education,
        text_extracted=result.raw_text_extracted,
    )
