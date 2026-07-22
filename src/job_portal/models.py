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
    # A notification belongs to exactly one recipient: a seeker OR an
    # employer, never both. seeker_id stays nullable=True (was
    # nullable=False/default=1) so employer-targeted rows can leave it
    # NULL — every existing call site already sets seeker_id explicitly,
    # so this is a widening change, not a behavior change for Sprint 1
    # notifications.
    seeker_id = Column(Integer, nullable=True, index=True)
    employer_id = Column(Integer, nullable=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=True, index=True)
    title = Column(String(200), nullable=False, default="")
    message = Column(Text, nullable=False, default="")
    is_read = Column(Integer, nullable=False, default=0)  # 0 = unread, 1 = read
    created_at = Column(DateTime, default=datetime.utcnow)
 
    application = relationship("Application")


class Conversation(Base):
    """One persistent thread per (seeker, employer) pair — WhatsApp/Telegram
    style: there's a single ongoing conversation with a contact, not a new
    thread per topic. A specific job can still be tagged onto individual
    messages within the thread (see Message.job_id) without splitting the
    conversation itself.
    """

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    seeker_id = Column(Integer, nullable=False, index=True)
    employer_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_message_at = Column(DateTime, default=datetime.utcnow)

    # "Delete conversation" (US messaging enhancement): hides the thread
    # from just that participant's inbox — the other party is unaffected,
    # and nothing is actually deleted. Mirrors Message.deleted_for_* below.
    # A new incoming/outgoing message un-hides it for both sides again
    # (see routes/messages.py) since an active conversation reappearing on
    # new activity matches how WhatsApp/Telegram "delete chat" behaves.
    hidden_for_seeker = Column(Integer, nullable=False, default=0)
    hidden_for_employer = Column(Integer, nullable=False, default=0)

    messages = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    sender_role = Column(String(10), nullable=False)  # "seeker" | "employer"
    sender_id = Column(Integer, nullable=False, index=True)
    body = Column(Text, nullable=False, default="")  # stored encrypted — see services/message_crypto.py
    # Optional "regarding this job" tag on an individual message — not
    # required, since US-40/41 allow general conversation too.
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    # US-46/47: "text" (default) or "interview_invite" — the latter carries
    # structured scheduling details via the linked InterviewInvite row.
    message_type = Column(String(20), nullable=False, default="text")
    is_read = Column(Integer, nullable=False, default=0)  # 0 = unread, 1 = read
    created_at = Column(DateTime, default=datetime.utcnow)

    # Edit (time-limited, enforced in the route layer)
    edited_at = Column(DateTime, nullable=True)

    # Delete: "for everyone" clears content and is visible-as-deleted to
    # both parties; "for me" only hides the row for that one participant's
    # own view — the other party is unaffected.
    is_deleted = Column(Integer, nullable=False, default=0)
    deleted_for_seeker = Column(Integer, nullable=False, default=0)
    deleted_for_employer = Column(Integer, nullable=False, default=0)

    # Attachment (image or document) — encrypted on disk the same way the
    # text body is (see services/message_crypto.py); served back out
    # through GET /api/messages/{id}/attachment, which decrypts on the fly
    # rather than being exposed via the static /uploads mount.
    attachment_filename = Column(String(255), nullable=True)
    attachment_url = Column(String(500), nullable=True)
    attachment_type = Column(String(20), nullable=True)  # "image" | "file"

    conversation = relationship("Conversation", back_populates="messages")
    job = relationship("Job")
    interview_invite = relationship(
        "InterviewInvite", uselist=False, back_populates="message", cascade="all, delete-orphan"
    )


class InterviewInvite(Base):
    """US-46/US-47: structured interview details attached to a message with
    message_type='interview_invite'. One-to-one with Message rather than
    extra columns bolted onto Message itself, since only this one message
    type needs these fields."""

    __tablename__ = "interview_invites"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, unique=True, index=True)
    scheduled_at = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=30)
    mode = Column(String(20), nullable=False, default="video")  # video | phone | in_person
    location_or_link = Column(Text, nullable=True, default="")
    notes = Column(Text, nullable=True, default="")
    status = Column(String(20), nullable=False, default="pending")  # pending | accepted | declined
    responded_at = Column(DateTime, nullable=True)

    message = relationship("Message", back_populates="interview_invite")