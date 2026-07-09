"""
Teammate B's routes: job discovery + seeker profile.

Covers:
  US-03  Upload resume
  US-12  Search jobs by keyword
  US-13  Filter jobs by location
  US-20  View job postings
  US-21  View job details
  US-22  Maintain skill profile
"""

import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from job_portal.database import get_db
from job_portal.models import Job, SeekerProfile
from job_portal.schemas import JobOut, SeekerProfileOut, SkillsUpdate

router = APIRouter(tags=["seeker"])

# Where uploaded resumes get stored for Sprint 1 (local disk).
# In a later sprint this can be swapped for Supabase Storage without
# changing the route logic below — only this constant + the save step.
RESUME_UPLOAD_DIR = os.getenv("RESUME_UPLOAD_DIR", "uploads/resumes")
ALLOWED_RESUME_TYPES = {"application/pdf", "application/msword",
                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MAX_RESUME_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


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
# ---------------------------------------------------------------------------


@router.get("/api/jobs", response_model=List[JobOut])
def list_jobs(
    keyword: Optional[str] = None,
    location: Optional[str] = None,
    db: Session = Depends(get_db),
) -> List[JobOut]:
    """
    List job postings, optionally filtered.

    - No params -> US-20: view all open job postings.
    - `keyword`  -> US-12: matches against title OR description (case-insensitive).
    - `location` -> US-13: matches against location (case-insensitive, partial match).
    - Both can be combined (AND logic).
    """
    query = db.query(Job).filter(Job.status == "open")

    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (Job.title.ilike(like)) | (Job.description.ilike(like))
        )

    if location:
        query = query.filter(Job.location.ilike(f"%{location}%"))

    jobs = query.order_by(Job.created_at.desc()).all()
    return [JobOut.from_job(job, credibility_score=_placeholder_score(job)) for job in jobs]


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
# US-22 — Maintain skill profile
# ---------------------------------------------------------------------------


@router.get("/api/seekers/{seeker_id}", response_model=SeekerProfileOut)
def get_seeker_profile(seeker_id: int, db: Session = Depends(get_db)) -> SeekerProfileOut:
    """Fetch a seeker's profile (creates an empty one if this is their first visit)."""
    profile = _get_or_create_profile(db, seeker_id)
    return SeekerProfileOut.from_profile(profile)


@router.put("/api/seekers/{seeker_id}/skills", response_model=SeekerProfileOut)
def update_skills(
    seeker_id: int, payload: SkillsUpdate, db: Session = Depends(get_db)
) -> SeekerProfileOut:
    """US-22: Replace the seeker's skill list so job matching can use it later."""
    profile = _get_or_create_profile(db, seeker_id)
    cleaned = [s.strip() for s in payload.skills if s.strip()]
    profile.skills = ",".join(cleaned)
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

    Sprint 1 stores the file on local disk under RESUME_UPLOAD_DIR and keeps
    the path in the DB. Swappable for Supabase Storage later without touching
    the calling code on the frontend.
    """
    if file.content_type not in ALLOWED_RESUME_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Resume must be a PDF or Word document (.pdf, .doc, .docx).",
        )

    contents = await file.read()
    if len(contents) > MAX_RESUME_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Resume must be under 5 MB.")

    os.makedirs(RESUME_UPLOAD_DIR, exist_ok=True)
    extension = os.path.splitext(file.filename or "")[1] or ".pdf"
    stored_name = f"{seeker_id}_{uuid.uuid4().hex}{extension}"
    stored_path = os.path.join(RESUME_UPLOAD_DIR, stored_name)

    with open(stored_path, "wb") as f:
        f.write(contents)

    profile = _get_or_create_profile(db, seeker_id)
    profile.resume_filename = file.filename
    profile.resume_url = stored_path
    db.commit()
    db.refresh(profile)
    return SeekerProfileOut.from_profile(profile)
