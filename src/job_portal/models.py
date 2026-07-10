"""
Shared database models.

IMPORTANT for the team: this file is shared across all three branches.
To avoid merge conflicts:
  - Teammate A owns the `Job` table's posting-management fields.
  - Teammate B (this file, Sprint 1) owns `SeekerProfile`, `WorkExperience`,
    and `Education`.
  - Teammate C will ADD `Application` and `Notification` classes at the
    bottom of this file in their own branch/commit — please don't
    reformat sections you don't own when merging.

NOTE: Job gained new columns (state, salary_min, salary_max, job_type,
positions_available, positions_filled) to support advanced search filters
and "spots remaining" display on the seeker side. Teammate A's create/edit
job posting form should be updated to let employers set these too.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from job_portal.database import Base


class Job(Base):
    """A job posting created by an employer (Teammate A owns create/update/delete)."""

    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    employer_id = Column(Integer, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    location = Column(String(200), nullable=True, default="")
    # Simple comma-separated skills string for Sprint 1 (e.g. "Python,SQL,FastAPI").
    # Good enough for keyword search; can be normalized into a join table later.
    skills_required = Column(Text, nullable=True, default="")
    status = Column(String(20), nullable=False, default="open")  # open / closed
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Added for advanced search filters + "spots remaining" (Teammate B) ---
    state = Column(String(100), nullable=True, default="")  # e.g. "Penang", "Remote"
    salary_min = Column(Integer, nullable=True)  # monthly, in RM
    salary_max = Column(Integer, nullable=True)
    job_type = Column(String(30), nullable=True, default="Full-time")
    # Full-time / Part-time / Contract / Internship / Remote
    positions_available = Column(Integer, nullable=False, default=1)
    positions_filled = Column(Integer, nullable=False, default=0)

    def skills_list(self) -> list[str]:
        """Helper: split the comma-separated skills string into a clean list."""
        if not self.skills_required:
            return []
        return [s.strip() for s in self.skills_required.split(",") if s.strip()]

    def positions_remaining(self) -> int:
        """How many open spots are left (never negative)."""
        return max(self.positions_available - self.positions_filled, 0)


class SeekerProfile(Base):
    """A job seeker's profile: personal info + resume + skills (Teammate B)."""

    __tablename__ = "seeker_profiles"

    id = Column(Integer, primary_key=True, index=True)
    seeker_id = Column(Integer, nullable=False, unique=True, index=True)

    # --- Personal info (added for the "real profile" upgrade) ---
    full_name = Column(String(150), nullable=True, default="")
    email = Column(String(150), nullable=True, default="")
    phone = Column(String(30), nullable=True, default="")
    bio = Column(Text, nullable=True, default="")

    resume_filename = Column(String(255), nullable=True)
    resume_url = Column(String(500), nullable=True)
    # Same simple comma-separated approach as Job.skills_required.
    skills = Column(Text, nullable=True, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    experience = relationship(
        "WorkExperience", back_populates="profile", cascade="all, delete-orphan"
    )
    education = relationship(
        "Education", back_populates="profile", cascade="all, delete-orphan"
    )

    def skills_list(self) -> list[str]:
        if not self.skills:
            return []
        return [s.strip() for s in self.skills.split(",") if s.strip()]


class WorkExperience(Base):
    """One past job entry on a seeker's profile."""

    __tablename__ = "work_experience"

    id = Column(Integer, primary_key=True, index=True)
    seeker_profile_id = Column(Integer, ForeignKey("seeker_profiles.id"), nullable=False, index=True)
    job_title = Column(String(150), nullable=False)
    company_name = Column(String(150), nullable=False)
    start_date = Column(String(30), nullable=True, default="")  # free text e.g. "Jan 2023"
    end_date = Column(String(30), nullable=True, default="")  # blank/"" means "Present"
    description = Column(Text, nullable=True, default="")

    profile = relationship("SeekerProfile", back_populates="experience")


class Education(Base):
    """One education entry on a seeker's profile."""

    __tablename__ = "education"

    id = Column(Integer, primary_key=True, index=True)
    seeker_profile_id = Column(Integer, ForeignKey("seeker_profiles.id"), nullable=False, index=True)
    institution = Column(String(150), nullable=False)
    degree = Column(String(150), nullable=True, default="")
    field_of_study = Column(String(150), nullable=True, default="")
    start_date = Column(String(30), nullable=True, default="")
    end_date = Column(String(30), nullable=True, default="")

    profile = relationship("SeekerProfile", back_populates="education")


# --- Teammate C: add Application and Notification classes below this line ---
