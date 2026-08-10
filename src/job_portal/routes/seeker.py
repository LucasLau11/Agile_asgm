import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from job_portal.database import get_db
from job_portal.models import Education, Job, SeekerProfile, WorkExperience
from job_portal.routes.auth import get_current_account_optional, require_role
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
from job_portal.services.credibility import compute_credibility_score, compute_credibility_reasons
from job_portal.services.matching import compute_skill_match
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
    sort_by: Optional[str] = None,
    account: Optional[dict] = Depends(get_current_account_optional),
    db: Session = Depends(get_db),
) -> List[JobOut]:
    """
    sort_by: "newest" (default), "salary_high", "salary_low", or "match"
    ("match" only has an effect when logged in as a seeker — otherwise
    there's nothing to sort by, so it silently falls back to "newest").

    Stays fully public: browsing never requires login. When a seeker IS
    logged in, results are personalized with match data automatically —
    no client-suppliable id is accepted or needed.
    """
    seeker_id: Optional[int] = account["id"] if account is not None and account["role"] == "seeker" else None
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
        query = query.filter(Job.salary_min.is_not(None), Job.salary_min >= salary_min)

    if sort_by == "salary_high":
        query = query.order_by(Job.salary_max.desc().nullslast())
    elif sort_by == "salary_low":
        query = query.order_by(Job.salary_min.asc().nullslast())
    else:
        query = query.order_by(Job.created_at.desc())

    jobs = query.all()

    seeker_skills: List[str] = []
    if seeker_id is not None:
        profile = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == seeker_id).first()
        seeker_skills = profile.skills_list() if profile else []

    results = []
    for job in jobs:
        match_percentage = None
        missing_skills: List[str] = []
        if seeker_id is not None:
            match = compute_skill_match(seeker_skills, job.skills_list())
            match_percentage = match["match_percentage"]
            missing_skills = match["missing_skills"]
        results.append(
            JobOut.from_job(
                job,
                credibility_score=compute_credibility_score(job, db),
                credibility_reasons=compute_credibility_reasons(job, db),
                match_percentage=match_percentage,
                missing_skills=missing_skills,
            )
        )

    if sort_by == "match" and seeker_id is not None:
        results.sort(key=lambda j: j.match_percentage or 0, reverse=True)

    return results

@router.get("/api/jobs/recommended", response_model=List[JobOut])
def recommended_jobs(
    min_match: int = 1,
    limit: int = 10,
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: Session = Depends(get_db),
) -> List[JobOut]:
    """Recommendations require login — there's no sensible anonymous
    recommendation, unlike list_jobs/get_job which stay public."""
    profile = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == seeker_id).first()
    seeker_skills = profile.skills_list() if profile else []
    if not seeker_skills:
        return []

    jobs = db.query(Job).filter(Job.status == "open").all()
    scored = []
    for job in jobs:
        match = compute_skill_match(seeker_skills, job.skills_list())
        if match["match_percentage"] >= min_match:
            scored.append((match, job))

    scored.sort(key=lambda pair: pair[0]["match_percentage"], reverse=True)
    return [
        JobOut.from_job(
            job,
            credibility_score=compute_credibility_score(job, db),
            credibility_reasons=compute_credibility_reasons(job, db),
            match_percentage=match["match_percentage"],
            missing_skills=match["missing_skills"],
        )
        for match, job in scored[:limit]
    ]


@router.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    account: Optional[dict] = Depends(get_current_account_optional),
    db: Session = Depends(get_db),
) -> JobOut:
    seeker_id: Optional[int] = account["id"] if account is not None and account["role"] == "seeker" else None
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    match_percentage = None
    missing_skills: List[str] = []
    if seeker_id is not None:
        profile = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == seeker_id).first()
        seeker_skills = profile.skills_list() if profile else []
        match = compute_skill_match(seeker_skills, job.skills_list())
        match_percentage = match["match_percentage"]
        missing_skills = match["missing_skills"]

    return JobOut.from_job(
        job,
        credibility_score=compute_credibility_score(job, db),
        credibility_reasons=compute_credibility_reasons(job, db),
        match_percentage=match_percentage,
        missing_skills=missing_skills,
    )

@router.get("/api/seekers/me", response_model=SeekerProfileOut)
def get_seeker_profile(
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: Session = Depends(get_db),
) -> SeekerProfileOut:
    """Fetch the logged-in seeker's own profile (creates an empty one if
    this is their first visit — registration doesn't pre-populate bio/phone/etc)."""
    profile = _get_or_create_profile(db, seeker_id)
    return SeekerProfileOut.from_profile(profile)


@router.put("/api/seekers/me", response_model=SeekerProfileOut)
def update_profile_info(
    payload: ProfileInfoUpdate,
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: Session = Depends(get_db),
) -> SeekerProfileOut:
    """Update personal info (name, email, phone, bio) — the 'real profile' fields.

    Since `email` doubles as the login identifier (see routes/auth.py), an
    update that would hand it to a different already-registered account is
    rejected — otherwise a seeker could lock another user out of their own
    login just by typing that user's email into their own profile form.
    """
    profile = _get_or_create_profile(db, seeker_id)

    new_email = payload.email.strip().lower()
    if new_email != (profile.email or "").strip().lower():
        from job_portal.models import Admin, Employer

        email_taken = (
            db.query(SeekerProfile)
            .filter(SeekerProfile.email == new_email, SeekerProfile.seeker_id != seeker_id)
            .first()
            is not None
            or db.query(Employer).filter(Employer.email == new_email).first() is not None
            or db.query(Admin).filter(Admin.email == new_email).first() is not None
        )
        if email_taken:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")

    profile.full_name = payload.full_name
    profile.email = payload.email
    profile.phone = payload.phone
    profile.bio = payload.bio
    db.commit()
    db.refresh(profile)
    return SeekerProfileOut.from_profile(profile)


@router.put("/api/seekers/me/skills", response_model=SeekerProfileOut)
def update_skills(
    payload: SkillsUpdate,
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: Session = Depends(get_db),
) -> SeekerProfileOut:
    """US-22: Replace the seeker's skill list so job matching can use it."""
    profile = _get_or_create_profile(db, seeker_id)
    cleaned = [s.strip() for s in payload.skills if s.strip()]
    profile.skills = ",".join(cleaned)
    db.commit()
    db.refresh(profile)
    return SeekerProfileOut.from_profile(profile)

# Work experience
@router.post("/api/seekers/me/experience", response_model=SeekerProfileOut, status_code=201)
def add_experience(
    payload: ExperienceIn,
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: Session = Depends(get_db),
) -> SeekerProfileOut:
    profile = _get_or_create_profile(db, seeker_id)
    entry = WorkExperience(seeker_profile_id=profile.id, **payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(profile)
    return SeekerProfileOut.from_profile(profile)


@router.delete("/api/seekers/me/experience/{experience_id}", response_model=SeekerProfileOut)
def delete_experience(
    experience_id: int,
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: Session = Depends(get_db),
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
@router.post("/api/seekers/me/education", response_model=SeekerProfileOut, status_code=201)
def add_education(
    payload: EducationIn,
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: Session = Depends(get_db),
) -> SeekerProfileOut:
    profile = _get_or_create_profile(db, seeker_id)
    entry = Education(seeker_profile_id=profile.id, **payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(profile)
    return SeekerProfileOut.from_profile(profile)


@router.delete("/api/seekers/me/education/{education_id}", response_model=SeekerProfileOut)
def delete_education(
    education_id: int,
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: Session = Depends(get_db),
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
@router.post("/api/seekers/me/resume", response_model=SeekerProfileOut, status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: Session = Depends(get_db),
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


@router.get("/api/seekers/me/resume/parse", response_model=ParsedResumeOut)
def parse_seeker_resume(
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: Session = Depends(get_db),
) -> ParsedResumeOut:
    """
    Scan the logged-in seeker's already-uploaded resume and extract
    suggested profile data (name, email, phone, skills) using lightweight
    text extraction + pattern matching (see services/resume_parser.py for
    the full approach and its honest limitations).
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