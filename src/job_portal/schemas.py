import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z.'\-\s]*$")
_PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\-\s()]*$")
_MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]
_DATE_PATTERN = re.compile(
    rf"^(?:(?:{'|'.join(_MONTH_NAMES)})\s)?(19|20)\d{{2}}$"
)

EDUCATION_LEVELS = [
    "SPM / High School",
    "STPM / A-Level / Foundation",
    "Certificate",
    "Diploma",
    "Bachelor's Degree",
    "Master's Degree",
    "PhD / Doctorate",
    "Professional Certification",
]

FIELDS_OF_STUDY = [
    "Computer Science",
    "Information Technology",
    "Software Engineering",
    "Data Science",
    "Business Administration",
    "Accounting",
    "Finance",
    "Marketing",
    "Economics",
    "Mechanical Engineering",
    "Electrical Engineering",
    "Civil Engineering",
    "Psychology",
    "Communications",
    "Law",
    "Medicine",
    "Nursing",
    "Education",
    "Hospitality & Tourism",
    "Design",
    "Architecture",
    "Mathematics",
    "Other",
]


def _validate_person_name(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("Name is required.")
    if any(ch.isdigit() for ch in value):
        raise ValueError("Name cannot contain numbers.")
    if not _NAME_PATTERN.match(value):
        raise ValueError("Name can only contain letters, spaces, apostrophes, and hyphens.")
    return value


def _validate_phone_number(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("Phone number is required.")
    if not _PHONE_PATTERN.match(value):
        raise ValueError("Phone number can only contain digits, spaces, dashes, and parentheses.")
    digit_count = sum(ch.isdigit() for ch in value)
    if digit_count < 7:
        raise ValueError("Phone number must have at least 7 digits.")
    return value


def _validate_date_field(value: Optional[str]) -> str:
    value = (value or "").strip()
    if not value:
        return value
    if not _DATE_PATTERN.match(value):
        raise ValueError("Date must be selected from the month/year picker (e.g. 'Jan 2023').")
    return value


class JobOut(BaseModel):
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
    credibility_score: Optional[int] = None
    match_percentage: Optional[int] = None

    @classmethod
    def from_job(
        cls, job, credibility_score: Optional[int] = None, match_percentage: Optional[int] = None
    ) -> "JobOut":
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


# ---------- Employer job management (Teammate A) ----------
#
# Status values stored on Job.status are "draft" / "open" / "closed" — NOT
# "active". The seeker-facing GET /api/jobs filters on Job.status == "open",
# so employer-side code keeps using "open" rather than introducing "active",
# to avoid silently breaking that query. The employer UI is free to
# *display* "open" as "Active" — that's a presentation choice, not a change
# to the stored value.
#
# Note: this reuses services/credibility.compute_credibility_score (added
# by a teammate) rather than defining a second, separate scoring function —
# one credibility number, shared by seeker and employer views alike.


def _looks_like_gibberish(text: str) -> bool:
    """
    Lightweight, non-NLP nonsense filter. Doesn't try to judge whether text
    is *meaningful* — just catches the obvious junk-input patterns:
      - purely numeric ("123")
      - very few distinct characters repeated to pad out a length
        requirement ("123123123123", "aaaaaaaaaa", "ababababab")
    """
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.isdigit():
        return True
    letters_only = stripped.replace(" ", "")
    if len(letters_only) >= 6 and len(set(letters_only.lower())) <= 3:
        return True
    return False


class JobCreate(BaseModel):
    """Body for POST /api/employer/jobs and PUT /api/employer/jobs/{id}.

    Mirrors the validation already enforced in the vanilla-JS frontend
    (title length, description length, at least one skill) — enforced here
    too because client-side checks can always be bypassed by calling the
    API directly. Also rejects obvious placeholder/junk content (see
    _looks_like_gibberish above) — not a guarantee of quality writing, just
    a filter for the "123123123" / "aaaaaaaa" style of test input.
    """

    title: str = Field(..., min_length=1, max_length=80)
    location: Optional[str] = Field("", max_length=200)
    state: Optional[str] = Field("", max_length=100)
    job_type: Optional[str] = Field("Full-time", max_length=30)
    salary_min: Optional[int] = Field(None, ge=0)
    salary_max: Optional[int] = Field(None, ge=0)
    skills_required: List[str] = Field(default_factory=list)
    description: str = Field(..., min_length=20)
    positions_available: int = Field(1, ge=1, le=50)

    @field_validator("title")
    @classmethod
    def _title_not_gibberish(cls, title: str) -> str:
        if _looks_like_gibberish(title):
            raise ValueError("Please enter a real job title.")
        return title

    @field_validator("description")
    @classmethod
    def _description_not_gibberish(cls, description: str) -> str:
        if _looks_like_gibberish(description):
            raise ValueError("Please write a real description, not placeholder text.")
        unique_words = {w.lower() for w in description.split()}
        if len(unique_words) < 3:
            raise ValueError("Please write a fuller description (a few different words, not just one repeated).")
        return description

    @field_validator("skills_required")
    @classmethod
    def _require_at_least_one_skill(cls, skills: List[str]) -> List[str]:
        cleaned = [s.strip() for s in skills if s.strip()]
        if not cleaned:
            raise ValueError("Add at least one required skill.")
        if len(cleaned) > 15:
            raise ValueError("A job posting can list at most 15 skills.")
        for skill in cleaned:
            if len(skill) < 2:
                raise ValueError(f'"{skill}" is too short to be a real skill.')
            if _looks_like_gibberish(skill):
                raise ValueError(f'"{skill}" doesn\'t look like a real skill.')
        return cleaned

    @field_validator("salary_max")
    @classmethod
    def _max_not_below_min(cls, salary_max, info):
        salary_min = info.data.get("salary_min")
        if salary_max is not None and salary_min is not None and salary_max < salary_min:
            raise ValueError("Maximum salary can't be lower than minimum salary.")
        return salary_max


class JobUpdate(JobCreate):
    """Editing a job replaces all editable fields at once — same shape as JobCreate."""

    pass


class EmployerJobOut(BaseModel):
    """Job data as returned to the employer managing it (richer than seeker-facing JobOut:
    includes draft postings, not just open ones)."""

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
    credibility_score: int = 0

    @classmethod
    def from_job(cls, job, credibility_score: int = 0) -> "EmployerJobOut":
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
        )


class ExperienceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_title: str
    company_name: str
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""
    description: Optional[str] = ""


class ExperienceIn(BaseModel):
    job_title: str = Field(..., min_length=1, max_length=150)
    company_name: str = Field(..., min_length=1, max_length=150)
    start_date: Optional[str] = Field("", max_length=30)
    end_date: Optional[str] = Field("", max_length=30)
    description: Optional[str] = Field("", max_length=2000)

    @field_validator("job_title", "company_name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("start_date", "end_date")
    @classmethod
    def _valid_date(cls, value: Optional[str]) -> str:
        return _validate_date_field(value)


class EducationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    institution: str
    degree: Optional[str] = ""
    field_of_study: Optional[str] = ""
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""


class EducationIn(BaseModel):
    institution: str = Field(..., min_length=1, max_length=150)
    degree: Optional[str] = Field("", max_length=150)
    field_of_study: Optional[str] = Field("", max_length=150)
    start_date: Optional[str] = Field("", max_length=30)
    end_date: Optional[str] = Field("", max_length=30)

    @field_validator("institution")
    @classmethod
    def _institution_not_blank(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("Institution cannot be blank.")
        return value

    @field_validator("degree")
    @classmethod
    def _valid_education_level(cls, value: Optional[str]) -> str:
        value = (value or "").strip()
        if value and value not in EDUCATION_LEVELS:
            raise ValueError(f"Education level must be one of: {', '.join(EDUCATION_LEVELS)}")
        return value

    @field_validator("field_of_study")
    @classmethod
    def _valid_field_of_study(cls, value: Optional[str]) -> str:
        value = (value or "").strip()
        if value and value not in FIELDS_OF_STUDY:
            raise ValueError(f"Field of study must be one of: {', '.join(FIELDS_OF_STUDY)}")
        return value

    @field_validator("start_date", "end_date")
    @classmethod
    def _valid_date(cls, value: Optional[str]) -> str:
        return _validate_date_field(value)


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

    skills: List[str] = Field(..., max_length=50)  
    @field_validator("skills")
    @classmethod
    def _cap_skill_length(cls, skills: List[str]) -> List[str]:
        return [s[:50] for s in skills]  


class ProfileInfoUpdate(BaseModel):

    full_name: str = Field(..., max_length=150)
    email: str = Field(..., max_length=150)
    phone: str = Field(..., max_length=30)
    bio: Optional[str] = Field("", max_length=2000)

    @field_validator("full_name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_person_name(value)

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str) -> str:
        return _validate_phone_number(value)

    @field_validator("email")
    @classmethod
    def _validate_email_format(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("Email is required.")
        from email_validator import EmailNotValidError, validate_email

        try:
            validate_email(value, check_deliverability=False)
        except EmailNotValidError:
            raise ValueError("Must be a valid email address, e.g. name@example.com")
        return value


class ExperienceSuggestion(BaseModel):
    job_title: str = ""
    company_name: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""


class EducationSuggestion(BaseModel):
    institution: str = ""
    degree: str = ""
    field_of_study: str = ""
    start_date: str = ""
    end_date: str = ""


# ---------- Messaging (US-40 / US-41 / US-42 / US-43) ----------


def _validate_message_body(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("Message cannot be empty.")
    if len(value) > 4000:
        raise ValueError("Message is too long (max 4000 characters).")
    return value


class MessageCreate(BaseModel):
    """Body for POST /api/messages.

    sender_role/sender_id identify who's sending (matches the "acting as"
    dev-user pattern used elsewhere — real auth arrives Sprint 3).
    recipient_id is the id of the other party, whose role is the opposite
    of sender_role. job_id is optional: a message can reference a specific
    job posting ("regarding this job") or be a general enquiry.
    """

    sender_role: str = Field(..., pattern="^(seeker|employer)$")
    sender_id: int
    recipient_id: int
    body: str = Field(..., min_length=1, max_length=4000)
    job_id: Optional[int] = None

    @field_validator("body")
    @classmethod
    def _body_not_blank(cls, value: str) -> str:
        return _validate_message_body(value)


class MessageEdit(BaseModel):
    """Body for PUT /api/messages/{id} — editing is time-limited (see
    EDIT_WINDOW_MINUTES in routes/messages.py) and sender-only."""

    body: str = Field(..., min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def _body_not_blank(cls, value: str) -> str:
        return _validate_message_body(value)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    sender_role: str
    sender_id: int
    body: str
    job_id: Optional[int] = None
    job_title: Optional[str] = None
    is_read: bool
    created_at: datetime
    is_edited: bool = False
    is_deleted: bool = False
    attachment_url: Optional[str] = None
    attachment_filename: Optional[str] = None
    attachment_type: Optional[str] = None

    @classmethod
    def from_message(cls, message, body: str) -> "MessageOut":
        """`body` is passed explicitly (already decrypted, and possibly
        replaced with a "This message was deleted" placeholder) rather than
        read off message.body directly, so this schema stays decoupled
        from the encryption layer — see routes/messages.py's _message_out().
        """
        return cls(
            id=message.id,
            conversation_id=message.conversation_id,
            sender_role=message.sender_role,
            sender_id=message.sender_id,
            body=body,
            job_id=message.job_id,
            job_title=message.job.title if message.job else None,
            is_read=bool(message.is_read),
            created_at=message.created_at,
            is_edited=message.edited_at is not None,
            is_deleted=bool(message.is_deleted),
            attachment_url=(
                f"/api/messages/{message.id}/attachment" if message.attachment_url else None
            ),
            attachment_filename=message.attachment_filename,
            attachment_type=message.attachment_type,
        )


class ConversationOut(BaseModel):
    """One row in the inbox list — the other party plus a preview of the
    most recent message, like a WhatsApp chat list entry."""

    id: int
    other_party_id: int
    other_party_name: str
    last_message_preview: str
    last_message_at: Optional[datetime] = None
    unread_count: int = 0


class ParsedResumeOut(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    bio: str = ""
    skills: List[str] = []
    experience: List[ExperienceSuggestion] = []
    education: List[EducationSuggestion] = []
    text_extracted: bool = True