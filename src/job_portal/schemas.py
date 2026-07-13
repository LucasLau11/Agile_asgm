"""Pydantic schemas (request/response shapes) for Teammate B's endpoints."""

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Shared validation patterns / option lists
#
# The frontend date fields are now <select> dropdowns (month + year) rather
# than free-text inputs, so a valid value is always "MMM YYYY" (e.g. "Jan
# 2023") or blank. We ALSO accept a bare 4-digit year ("2023") here — not
# because the frontend produces that anymore, but because the resume-scan
# "apply suggestions" flow feeds parsed dates through these same endpoints,
# and the parser sometimes can only find a year, not a month.
# ---------------------------------------------------------------------------

_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z.'\-\s]*$")
# Malaysian + generic international phone characters: digits, spaces,
# dashes, parentheses, and a leading +. No letters allowed.
_PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\-\s()]*$")
_MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]
_DATE_PATTERN = re.compile(
    rf"^(?:(?:{'|'.join(_MONTH_NAMES)})\s)?(19|20)\d{{2}}$"
)

# Options for the education-level dropdown (renamed from the old free-text
# "Degree" field, since seekers may be diploma/degree/master/PhD holders etc).
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

# Options for the field-of-study dropdown.
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
    """Used for start_date/end_date. Blank is always allowed (blank end_date
    means "Present"; blank start_date just means unspecified)."""
    value = (value or "").strip()
    if not value:
        return value
    if not _DATE_PATTERN.match(value):
        raise ValueError("Date must be selected from the month/year picker (e.g. 'Jan 2023').")
    return value


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
    institution: str = Field(..., min_length=1, max_length=150)
    # NOTE: this field stores the seeker's education LEVEL (Diploma / Bachelor's /
    # Master's / PhD / etc — the frontend labels it "Education Level" and presents
    # it as a dropdown). Kept as `degree` at the schema/DB level to avoid a
    # migration; only the label + allowed values changed.
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

    skills: List[str] = Field(..., max_length=50)  # cap the number of skills, not just their length

    @field_validator("skills")
    @classmethod
    def _cap_skill_length(cls, skills: List[str]) -> List[str]:
        return [s[:50] for s in skills]  # cap each individual skill's length


class ProfileInfoUpdate(BaseModel):
    """Body for PUT /api/seekers/{seeker_id} (personal info fields)."""

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


# ---------- Resume parsing (NLP-lite auto-fill suggestions) ----------


class ExperienceSuggestion(BaseModel):
    """
    A resume-parsed work experience suggestion. Deliberately more lenient
    than ExperienceIn (which is used for actual create requests) — every
    field is optional here, because the parser sometimes can't confidently
    split a line into title vs. company, and a suggestion with a blank
    field the user can fill in themselves is far better than the whole
    entry being dropped or the request erroring out.
    """

    job_title: str = ""
    company_name: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""


class EducationSuggestion(BaseModel):
    """Lenient counterpart to EducationIn — see ExperienceSuggestion docstring."""

    institution: str = ""
    degree: str = ""
    field_of_study: str = ""
    start_date: str = ""
    end_date: str = ""


class ParsedResumeOut(BaseModel):
    """
    Response for GET /api/seekers/{seeker_id}/resume/parse.

    These are SUGGESTIONS extracted from the resume text — never applied
    to the profile automatically. The frontend shows them for the user to
    review and choose to apply via the normal profile/skills/experience/
    education endpoints.
    """

    full_name: str = ""
    email: str = ""
    phone: str = ""
    bio: str = ""
    skills: List[str] = []
    experience: List[ExperienceSuggestion] = []
    education: List[EducationSuggestion] = []
    text_extracted: bool = True
