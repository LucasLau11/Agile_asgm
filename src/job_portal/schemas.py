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
    skills_required: List[str] = []
    status: str
    created_at: datetime
    # Filled in by Teammate C's credibility service; defaults to None until
    # that integration lands so Teammate B's endpoints work standalone.
    credibility_score: Optional[int] = None

    @classmethod
    def from_job(cls, job, credibility_score: Optional[int] = None) -> "JobOut":
        """Build a JobOut from a Job ORM object, splitting the skills string."""
        return cls(
            id=job.id,
            employer_id=job.employer_id,
            title=job.title,
            description=job.description,
            location=job.location,
            skills_required=job.skills_list(),
            status=job.status,
            created_at=job.created_at,
            credibility_score=credibility_score,
        )


# ---------- Seeker profile ----------


class SeekerProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seeker_id: int
    resume_filename: Optional[str] = None
    resume_url: Optional[str] = None
    skills: List[str] = []

    @classmethod
    def from_profile(cls, profile) -> "SeekerProfileOut":
        # profile.resume_url is a raw disk path like "uploads/resumes/xxx.pdf"
        # (relative to the server's working directory). Add a leading slash
        # so the frontend gets a real URL it can open directly, matching the
        # /uploads mount in main.py.
        url = f"/{profile.resume_url}" if profile.resume_url else None
        return cls(
            seeker_id=profile.seeker_id,
            resume_filename=profile.resume_filename,
            resume_url=url,
            skills=profile.skills_list(),
        )


class SkillsUpdate(BaseModel):
    """Body for PUT /api/seekers/{seeker_id}/skills"""

    skills: List[str]