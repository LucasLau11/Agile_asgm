"""Pydantic schemas (request/response shapes) for Teammate B's endpoints."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# ---------- Job (read-only from Teammate B's side) ----------


class JobOut(BaseModel):
    """Job data as returned to job seekers (Browse / Search / Detail pages)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    employer_id: int
    title: str
    description: str
    location: Optional[str] = ""
    state: Optional[str] = ""
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    job_type: Optional[str] = "Full-time"
    skills_required: List[str] = []
    status: str
    created_at: datetime
    positions_available: int = 1
    positions_filled: int = 0
    positions_remaining: int = 1
    # Filled in by Teammate C's credibility service; defaults to None until
    # that integration lands so Teammate B's endpoints work standalone.
    credibility_score: Optional[int] = None
    # Filled in only by the /api/jobs/recommended endpoint; None elsewhere.
    match_percentage: Optional[int] = None

    @classmethod
    def from_job(
        cls, job, credibility_score: Optional[int] = None, match_percentage: Optional[int] = None
    ) -> "JobOut":
        """Build a JobOut from a Job ORM object, splitting the skills string."""
        return cls(
            id=job.id,
            employer_id=job.employer_id,
            title=job.title,
            description=job.description,
            location=job.location,
            state=job.state,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            job_type=job.job_type,
            skills_required=job.skills_list(),
            status=job.status,
            created_at=job.created_at,
            positions_available=job.positions_available,
            positions_filled=job.positions_filled,
            positions_remaining=job.positions_remaining(),
            credibility_score=credibility_score,
            match_percentage=match_percentage,
        )


# ---------- Work experience ----------


class ExperienceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_title: str
    company_name: str
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""
    description: Optional[str] = ""


class ExperienceIn(BaseModel):
    job_title: str
    company_name: str
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""
    description: Optional[str] = ""


# ---------- Education ----------


class EducationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    institution: str
    degree: Optional[str] = ""
    field_of_study: Optional[str] = ""
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""


class EducationIn(BaseModel):
    institution: str
    degree: Optional[str] = ""
    field_of_study: Optional[str] = ""
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""


# ---------- Seeker profile ----------


class SeekerProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seeker_id: int
    full_name: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    bio: Optional[str] = ""
    resume_filename: Optional[str] = None
    resume_url: Optional[str] = None
    skills: List[str] = []
    experience: List[ExperienceOut] = []
    education: List[EducationOut] = []

    @classmethod
    def from_profile(cls, profile) -> "SeekerProfileOut":
        # profile.resume_url is a raw disk path like "uploads/resumes/xxx.pdf"
        # (relative to the server's working directory). Add a leading slash
        # so the frontend gets a real URL it can open directly, matching the
        # /uploads mount in main.py.
        url = f"/{profile.resume_url}" if profile.resume_url else None
        return cls(
            seeker_id=profile.seeker_id,
            full_name=profile.full_name or "",
            email=profile.email or "",
            phone=profile.phone or "",
            bio=profile.bio or "",
            resume_filename=profile.resume_filename,
            resume_url=url,
            skills=profile.skills_list(),
            experience=[ExperienceOut.model_validate(e) for e in profile.experience],
            education=[EducationOut.model_validate(e) for e in profile.education],
        )


class SkillsUpdate(BaseModel):
    """Body for PUT /api/seekers/{seeker_id}/skills"""

    skills: List[str]


class ProfileInfoUpdate(BaseModel):
    """Body for PUT /api/seekers/{seeker_id} (personal info fields)."""

    full_name: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    bio: Optional[str] = ""
