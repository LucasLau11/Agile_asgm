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
from job_portal.services.credibility import compute_credibility_score
from job_portal.services.file_validation import (
    ALLOWED_EXTENSIONS,
    MAX_RESUME_SIZE_BYTES,
    detect_safe_extension,
    sanitize_display_filename,
)
from job_portal.services.resume_parser import parse_resume

router = APIRouter(tags=["seeker"])

# Where uploaded resumes get stored local disk.
RESUME_UPLOAD_DIR = os.getenv("RESUME_UPLOAD_DIR", "uploads/resumes")

# fetch a seeker's profile, creating an empty one if it doesn't exist yet.
def _get_or_create_profile(db: Session, seeker_id: int) -> SeekerProfile:
    profile = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == seeker_id).first()
    if profile is None:
        profile = SeekerProfile(seeker_id=seeker_id, skills="")
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


# Browse, search, and filter job postings

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
    return [
        JobOut.from_job(job, credibility_score=compute_credibility_score(job, db))
        for job in jobs
    ]

# Resume/skill-based job matching 
def _match_percentage(seeker_skills: list[str], job_skills: list[str]) -> int:
    """
    Simple overlap-based matching algorithm.

    Score = (number of the job's required skills that the seeker has)
             / (total number of the job's required skills) * 100
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
        JobOut.from_job(
            job,
            credibility_score=compute_credibility_score(job, db),
            match_percentage=pct,
        )
        for pct, job in scored[:limit]
    ]


@router.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobOut:
    """US-21: View full details of a single job posting."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut.from_job(job, credibility_score=compute_credibility_score(job, db))


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

# Work experience 
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


# Education
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


# US-03 — Upload resume
@router.post("/api/seekers/{seeker_id}/resume", response_model=SeekerProfileOut, status_code=201)
async def upload_resume(
    seeker_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> SeekerProfileOut:

    contents = await file.read()

    if len(contents) > MAX_RESUME_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Resume must be under 5 MB.")

    safe_extension = detect_safe_extension(contents)
    if safe_extension is None:
        raise HTTPException(
            status_code=400,
            detail="Resume must be a genuine PDF or Word (.docx) document. "
            "The file's content didn't match either of those formats.",
        )

    os.makedirs(RESUME_UPLOAD_DIR, exist_ok=True)
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