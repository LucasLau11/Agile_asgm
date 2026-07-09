"""
Shared database models.

IMPORTANT for the team: this file is shared across all three branches.
To avoid merge conflicts:
  - Teammate A owns the `Job` table's posting-management fields.
  - Teammate B (this file, Sprint 1) owns `SeekerProfile`.
  - Teammate C will ADD `Application` and `Notification` classes at the
    bottom of this file in their own branch/commit — please don't
    reformat sections you don't own when merging.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

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

    def skills_list(self) -> list[str]:
        """Helper: split the comma-separated skills string into a clean list."""
        if not self.skills_required:
            return []
        return [s.strip() for s in self.skills_required.split(",") if s.strip()]


class SeekerProfile(Base):
    """A job seeker's profile: resume + skill list (Teammate B, US-03 / US-22)."""

    __tablename__ = "seeker_profiles"

    id = Column(Integer, primary_key=True, index=True)
    seeker_id = Column(Integer, nullable=False, unique=True, index=True)
    resume_filename = Column(String(255), nullable=True)
    resume_url = Column(String(500), nullable=True)
    # Same simple comma-separated approach as Job.skills_required.
    skills = Column(Text, nullable=True, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def skills_list(self) -> list[str]:
        if not self.skills:
            return []
        return [s.strip() for s in self.skills.split(",") if s.strip()]


# --- Teammate C: add Application and Notification classes below this line ---
