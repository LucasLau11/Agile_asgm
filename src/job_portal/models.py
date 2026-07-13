# Shared database models.

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from job_portal.database import Base


class Job(Base):

    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    employer_id = Column(Integer, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    location = Column(String(200), nullable=True, default="")
    skills_required = Column(Text, nullable=True, default="")
    status = Column(String(20), nullable=False, default="open") 
    created_at = Column(DateTime, default=datetime.utcnow)

    state = Column(String(100), nullable=True, default="")  
    salary_min = Column(Integer, nullable=True)  
    salary_max = Column(Integer, nullable=True)
    job_type = Column(String(30), nullable=True, default="Full-time")
    positions_available = Column(Integer, nullable=False, default=1)
    positions_filled = Column(Integer, nullable=False, default=0)

    def skills_list(self) -> list[str]:
        if not self.skills_required:
            return []
        return [s.strip() for s in self.skills_required.split(",") if s.strip()]

    def positions_remaining(self) -> int:
        return max(self.positions_available - self.positions_filled, 0)


class SeekerProfile(Base):
    __tablename__ = "seeker_profiles"

    id = Column(Integer, primary_key=True, index=True)
    seeker_id = Column(Integer, nullable=False, unique=True, index=True)

    full_name = Column(String(150), nullable=True, default="")
    email = Column(String(150), nullable=True, default="")
    phone = Column(String(30), nullable=True, default="")
    bio = Column(Text, nullable=True, default="")

    resume_filename = Column(String(255), nullable=True)
    resume_url = Column(String(500), nullable=True)
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

    __tablename__ = "work_experience"

    id = Column(Integer, primary_key=True, index=True)
    seeker_profile_id = Column(Integer, ForeignKey("seeker_profiles.id"), nullable=False, index=True)
    job_title = Column(String(150), nullable=False)
    company_name = Column(String(150), nullable=False)
    start_date = Column(String(30), nullable=True, default="")  
    end_date = Column(String(30), nullable=True, default="")  
    description = Column(Text, nullable=True, default="")

    profile = relationship("SeekerProfile", back_populates="experience")


class Education(Base):

    __tablename__ = "education"

    id = Column(Integer, primary_key=True, index=True)
    seeker_profile_id = Column(Integer, ForeignKey("seeker_profiles.id"), nullable=False, index=True)
    institution = Column(String(150), nullable=False)
    degree = Column(String(150), nullable=True, default="")
    field_of_study = Column(String(150), nullable=True, default="")
    start_date = Column(String(30), nullable=True, default="")
    end_date = Column(String(30), nullable=True, default="")

    profile = relationship("SeekerProfile", back_populates="education")


class Application(Base):

    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    seeker_id = Column(Integer, nullable=False, index=True, default=1)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    seeker_name = Column(String(150), nullable=False, default="Aisha")
    email = Column(String(150), nullable=True, default="aisha@email.com")
    job_title = Column(String(200), nullable=False, default="Backend Engineer")
    company_name = Column(String(150), nullable=False, default="ABC Technologies")
    skills = Column(String(250), nullable=True, default="Python, FastAPI, SQL")
    status = Column(String(50), nullable=False, default="Applied")  # Applied, Screening, Interview, Rejected, Offered
    applied_date = Column(String(50), nullable=False, default="10 July 2026")
    cover_letter = Column(Text, nullable=True, default="")
    experience = Column(Text, nullable=True, default="")
    notes = Column(Text, nullable=True, default="")

    job = relationship("Job", back_populates="applications" if hasattr(Job, "applications") else None)

class Notification(Base): 
    __tablename__ = "notifications"
 
    id = Column(Integer, primary_key=True, index=True)
    seeker_id = Column(Integer, nullable=False, index=True, default=1)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True, index=True)
    title = Column(String(200), nullable=False, default="")
    message = Column(Text, nullable=False, default="")
    is_read = Column(Integer, nullable=False, default=0)  # 0 = unread, 1 = read
    created_at = Column(DateTime, default=datetime.utcnow)
 
    application = relationship("Application")