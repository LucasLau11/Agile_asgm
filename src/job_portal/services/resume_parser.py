"""
Resume parsing: extracts text from an uploaded resume (PDF or DOCX) and
pulls out structured data — name, email, phone, and skills — to help
pre-fill the seeker's profile.

Honest scope note: this is NOT a machine-learning NER model (like spaCy).
It's a lightweight, dependency-friendly combination of:
  - regex pattern matching (email, phone — these have a reliable, learnable
    shape, so regex is actually the RIGHT tool here, not a compromise)
  - a skills dictionary/keyword lookup (matches resume text against a list
    of ~80 common tech + soft skills)
  - simple positional heuristics (a person's name is very reliably the
    first non-empty line of a resume)

This trades some accuracy for being fast, fully offline (no model download
or API calls needed), and easy for the team to understand/extend — a good
fit for a Sprint 1 feature. A full NER model (spaCy/transformers) would
extract more (e.g. company names, degree titles) but adds a large
dependency and slower processing; flagged as a possible Sprint 2/3
upgrade rather than built now.

IMPORTANT: results are SUGGESTIONS ONLY. The API never auto-saves parsed
data to the profile — it returns it for the frontend to show the user for
review/confirmation before anything is applied. Resumes are messy and
this parser WILL get things wrong sometimes; silently overwriting a
seeker's real profile data would be worse than not offering the feature.
"""

import io
import re
from dataclasses import dataclass, field

import pdfplumber
from docx import Document

# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def extract_text(contents: bytes, extension: str) -> str:
    """
    Extract raw text from resume file bytes. `extension` must be one of
    the SAFE extensions already validated by file_validation.detect_safe_extension
    — never derived from user input directly.
    """
    if extension == ".pdf":
        return _extract_pdf_text(contents)
    if extension == ".docx":
        return _extract_docx_text(contents)
    if extension == ".doc":
        # Legacy binary .doc format has no good pure-Python text extractor
        # without extra system dependencies (e.g. antiword). Rather than
        # silently returning nothing, we're explicit about the limitation.
        return ""
    return ""


def _extract_pdf_text(contents: bytes) -> str:
    text_parts = []
    with pdfplumber.open(io.BytesIO(contents)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def _extract_docx_text(contents: bytes) -> str:
    doc = Document(io.BytesIO(contents))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


# ---------------------------------------------------------------------------
# Structured data extraction
# ---------------------------------------------------------------------------

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Covers common Malaysian formats (012-345 6789, +60123456789) and generic
# international formats loosely. Deliberately permissive — a false-positive
# "phone number" the user can just delete is much better than missing a
# real one because the regex was too strict.
_PHONE_PATTERN = re.compile(
    r"(\+?6?0?1[0-9][-.\s]?\d{3,4}[-.\s]?\d{4}|\+\d{1,3}[-.\s]?\d{2,4}[-.\s]?\d{3,4}[-.\s]?\d{3,4})"
)

# A deliberately-not-exhaustive dictionary of common skills to scan for.
# Extend this list as the team notices real resumes mentioning skills that
# aren't being picked up.
SKILLS_VOCABULARY = [
    # Languages
    "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "PHP", "Ruby",
    "Go", "Swift", "Kotlin", "R", "MATLAB", "SQL",
    # Web / frameworks
    "React", "Vue", "Angular", "Node.js", "Express", "Django", "Flask",
    "FastAPI", "Spring", "Laravel", "HTML", "CSS", "Tailwind", "Bootstrap",
    # Data / ML
    "Pandas", "NumPy", "TensorFlow", "PyTorch", "scikit-learn", "Excel",
    "Power BI", "Tableau",
    # Infra / tools
    "Docker", "Kubernetes", "AWS", "Azure", "GCP", "CI/CD", "Git", "Linux",
    "Jenkins", "Terraform",
    # Databases
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "SQLite", "Firebase",
    # Design
    "Figma", "Photoshop", "Illustrator", "User Research", "UI/UX",
    # Soft/business skills often listed explicitly on resumes
    "Project Management", "Agile", "Scrum", "Communication", "Leadership",
    "Public Speaking", "Data Analysis", "Machine Learning",
]


def _guess_name(text: str) -> str:
    """
    Heuristic: a resume's very first non-empty line is, in the overwhelming
    majority of real-world resumes, the candidate's name (it's the header/
    title of the document). We sanity-check it looks name-like (2-4 words,
    no digits, no @ symbol) before trusting it — if that check fails, we
    return an empty string rather than guessing wrong.
    """
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        words = candidate.split()
        looks_like_name = (
            2 <= len(words) <= 4
            and not any(char.isdigit() for char in candidate)
            and "@" not in candidate
            and len(candidate) < 60
        )
        return candidate if looks_like_name else ""
    return ""


def _extract_email(text: str) -> str:
    match = _EMAIL_PATTERN.search(text)
    return match.group(0) if match else ""


def _extract_phone(text: str) -> str:
    match = _PHONE_PATTERN.search(text)
    return match.group(0).strip() if match else ""


def _extract_skills(text: str) -> list[str]:
    """Case-insensitive match against SKILLS_VOCABULARY, preserving the
    canonical casing from the vocabulary (not however it appeared in the
    resume) so results look consistent regardless of how the applicant
    formatted their resume."""
    text_lower = text.lower()
    found = []
    for skill in SKILLS_VOCABULARY:
        # Word-boundary match so "R" doesn't match inside "Marketing", etc.
        pattern = r"\b" + re.escape(skill.lower()) + r"\b"
        if re.search(pattern, text_lower):
            found.append(skill)
    return found


# ---------------------------------------------------------------------------
# Work experience & education section extraction
#
# This is the hardest part of resume parsing without a trained ML model —
# job titles, dates, and companies are formatted a hundred different ways
# across real resumes. The approach below: find section headers, split each
# section into entries wherever a line contains a date range (a reliable
# signal that a new role/degree is starting), then apply best-effort
# heuristics to each entry. It will get some entries wrong or miss unusual
# formats — that's exactly why results are suggestions the user reviews,
# never auto-saved.
# ---------------------------------------------------------------------------

_EXPERIENCE_HEADERS = {
    "experience", "work experience", "employment history",
    "professional experience", "career history", "work history",
}
_EDUCATION_HEADERS = {
    "education", "academic background", "educational background",
    "academic qualifications", "qualifications",
}
# Any of these appearing as their own line marks the END of whatever
# section came before it (used so we know where Experience/Education stop).
_ALL_SECTION_HEADERS = _EXPERIENCE_HEADERS | _EDUCATION_HEADERS | {
    "skills", "technical skills", "projects", "summary", "objective",
    "certifications", "references", "achievements", "languages",
    "interests", "publications", "contact", "personal details", "profile",
}

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*"
_YEAR = r"(?:19|20)\d{2}"
_DATE_TOKEN = rf"(?:{_MONTH}{_YEAR}|{_YEAR})"
_DATE_RANGE_PATTERN = re.compile(
    rf"({_DATE_TOKEN})\s*(?:[-–—]|to)\s*({_DATE_TOKEN}|Present|Current|Now)",
    re.IGNORECASE,
)

_DEGREE_KEYWORDS = [
    "Bachelor", "Master", "PhD", "Doctorate", "Diploma", "Associate",
    "B.Sc", "BSc", "M.Sc", "MSc", "B.Eng", "BEng", "M.Eng", "MEng",
    "B.A.", "BA", "M.A.", "MA", "MBA", "Foundation", "Certificate",
]
_INSTITUTION_KEYWORDS = [
    "University", "Universiti", "College", "Institute", "Politeknik",
    "Polytechnic", "School",
]


def _split_into_sections(text: str) -> dict[str, str]:
    """
    Walk the resume line by line, tagging which known section each line
    belongs to. Lines before the first recognized header aren't attributed
    to any section (they're usually the name/contact block at the top).
    """
    sections: dict[str, list[str]] = {}
    current_section = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        normalized = line.lower().rstrip(":").strip()
        if normalized in _ALL_SECTION_HEADERS:
            if normalized in _EXPERIENCE_HEADERS:
                current_section = "experience"
            elif normalized in _EDUCATION_HEADERS:
                current_section = "education"
            else:
                current_section = None  # a recognized-but-uninteresting header (e.g. "Skills")
            sections.setdefault(current_section, []) if current_section else None
            continue

        if current_section:
            sections.setdefault(current_section, []).append(line)

    return {name: "\n".join(lines) for name, lines in sections.items()}


def _looks_like_entry_header(line: str) -> bool:
    """
    Heuristic: does this line look like it's starting a NEW entry (a job
    title/company line, or an institution/degree line) rather than being a
    description sentence continuing the previous entry?

    Signals: short, doesn't end in a period (description sentences usually
    do), and either uses a common "Title, Company" style delimiter or is
    mostly Title Case (how institutions/job titles are usually written).
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 80 or stripped.endswith("."):
        return False
    if any(delim in stripped for delim in [",", " at ", "|"]):
        return True
    words = stripped.split()
    if not words:
        return False
    capitalized = sum(1 for w in words if w[0].isupper())
    return capitalized / len(words) >= 0.6


def _split_entries(block_text: str) -> list[list[str]]:
    """
    Split a section's text into per-entry chunks.

    Common resume layout is "Title/Company" then, on a following line, the
    date range, then description lines. A new entry begins when we hit a
    header-shaped line AFTER we've already seen a date for the current
    entry — NOT simply "whenever a date appears", since the date usually
    comes right after (not on the same line as) the title.
    """
    lines = [l for l in block_text.splitlines() if l.strip()]
    entries: list[list[str]] = []
    current: list[str] = []
    date_found_for_current = False

    for line in lines:
        if _DATE_RANGE_PATTERN.search(line):
            current.append(line)
            date_found_for_current = True
            continue

        if date_found_for_current and _looks_like_entry_header(line):
            if current:
                entries.append(current)
            current = [line]
            date_found_for_current = False
        else:
            current.append(line)

    if current:
        entries.append(current)
    return entries


def _parse_experience_entry(lines: list[str]) -> dict:
    if not lines:
        return {"job_title": "", "company_name": "", "start_date": "", "end_date": "", "description": ""}

    date_line = next((l for l in lines if _DATE_RANGE_PATTERN.search(l)), "")
    date_match = _DATE_RANGE_PATTERN.search(date_line) if date_line else None
    start_date = date_match.group(1).strip() if date_match else ""
    end_date = date_match.group(2).strip() if date_match else ""
    if end_date.lower() in ("present", "current", "now"):
        end_date = ""  # matches our schema convention: blank end_date = "Present"

    # The title/company line is whichever non-date line comes first in the entry.
    title_line = next((l for l in lines if l != date_line), "")

    job_title, company_name = "", ""
    if " at " in title_line.lower():
        idx = title_line.lower().index(" at ")
        job_title, company_name = title_line[:idx].strip(), title_line[idx + 4:].strip()
    elif "," in title_line:
        job_title, company_name = (p.strip() for p in title_line.split(",", 1))
    elif "|" in title_line:
        job_title, company_name = (p.strip() for p in title_line.split("|", 1))
    else:
        job_title = title_line.strip()

    description_lines = [l for l in lines if l != title_line and l != date_line]
    description = " ".join(description_lines).strip()

    return {
        "job_title": job_title[:150],
        "company_name": company_name[:150],
        "start_date": start_date[:30],
        "end_date": end_date[:30],
        "description": description[:2000],
    }


def _parse_education_entry(lines: list[str]) -> dict:
    full_text = " ".join(lines)
    date_match = _DATE_RANGE_PATTERN.search(full_text)
    start_date = date_match.group(1).strip() if date_match else ""
    end_date = date_match.group(2).strip() if date_match else ""
    if end_date.lower() in ("present", "current", "now"):
        end_date = ""

    institution = next(
        (l.strip() for l in lines if any(kw.lower() in l.lower() for kw in _INSTITUTION_KEYWORDS)),
        "",
    )
    degree = next(
        (kw for kw in _DEGREE_KEYWORDS if re.search(rf"\b{re.escape(kw)}\b", full_text, re.IGNORECASE)),
        "",
    )
    field_of_study = ""
    field_match = re.search(r"\bin\s+([A-Z][A-Za-z\s]{2,40})", full_text)
    if field_match:
        field_of_study = field_match.group(1).strip()

    # Fall back to the entry's first non-date line as the institution if
    # none of the known keywords matched — better than leaving it blank.
    if not institution:
        non_date_lines = [l for l in lines if not _DATE_RANGE_PATTERN.search(l)]
        institution = non_date_lines[0].strip() if non_date_lines else ""

    return {
        "institution": institution[:150],
        "degree": degree[:150],
        "field_of_study": field_of_study[:150],
        "start_date": start_date[:30],
        "end_date": end_date[:30],
    }


def _extract_experience(text: str) -> list[dict]:
    sections = _split_into_sections(text)
    block = sections.get("experience", "")
    if not block:
        return []
    entries = _split_entries(block)
    parsed = [_parse_experience_entry(lines) for lines in entries]
    # Drop entries where we couldn't even find a job title — not useful to suggest.
    return [e for e in parsed if e["job_title"]]


def _extract_education(text: str) -> list[dict]:
    sections = _split_into_sections(text)
    block = sections.get("education", "")
    if not block:
        return []
    entries = _split_entries(block)
    parsed = [_parse_education_entry(lines) for lines in entries]
    return [e for e in parsed if e["institution"]]


@dataclass
class ParsedResume:
    full_name: str = ""
    email: str = ""
    phone: str = ""
    skills: list[str] = field(default_factory=list)
    experience: list[dict] = field(default_factory=list)
    education: list[dict] = field(default_factory=list)
    raw_text_extracted: bool = False  # lets the frontend show a helpful
    # message if we genuinely couldn't read anything (e.g. a scanned/
    # image-only PDF with no real text layer, or an old .doc file).


def parse_resume(contents: bytes, extension: str) -> ParsedResume:
    text = extract_text(contents, extension)
    if not text.strip():
        return ParsedResume(raw_text_extracted=False)

    return ParsedResume(
        full_name=_guess_name(text),
        email=_extract_email(text),
        phone=_extract_phone(text),
        skills=_extract_skills(text),
        experience=_extract_experience(text),
        education=_extract_education(text),
        raw_text_extracted=True,
    )
