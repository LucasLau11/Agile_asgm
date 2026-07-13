import difflib
import io
import re
from dataclasses import dataclass, field

import pdfplumber
from docx import Document

from job_portal.schemas import EDUCATION_LEVELS, FIELDS_OF_STUDY

# Text extraction
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
        return ""
    return ""


def _extract_pdf_text(contents: bytes) -> str:
    text_parts = []
    with pdfplumber.open(io.BytesIO(contents)) as pdf:
        for page in pdf.pages:
            page_text = _extract_page_text(page)
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def _extract_page_text(page) -> str:
    words = page.extract_words()
    if not words or not page.width:
        return page.extract_text() or ""

    gutter = _find_column_gutter(words, page.width)
    if gutter is None:
        return page.extract_text() or ""

    left_words = [w for w in words if w["x0"] < gutter]
    right_words = [w for w in words if w["x0"] >= gutter]
    if not left_words or not right_words:
        return page.extract_text() or ""

    columns = sorted([left_words, right_words], key=len, reverse=True)
    return "\n".join(_words_to_text(col) for col in columns)


def _find_column_gutter(words: list, page_width: float) -> float | None:
    lines = _group_words_into_lines(words)
    if len(lines) < 4:
        return None

    xs = sorted(w["x0"] for w in words)
    low, high = page_width * 0.15, page_width * 0.85
    candidates = sorted(
        {(a + b) / 2 for a, b in zip(xs, xs[1:]) if low < (a + b) / 2 < high and b - a > page_width * 0.06},
        key=lambda mid: mid,
    )

    best_gutter = None
    best_gap = 0.0
    for gutter in candidates:
        straddling = 0
        left_lines = right_lines = 0
        for line_words in lines:
            min_x0 = min(w["x0"] for w in line_words)
            max_x1 = max(w["x1"] for w in line_words)
            if min_x0 < gutter and max_x1 > gutter:
                straddling += 1
            elif max_x1 <= gutter:
                left_lines += 1
            else:
                right_lines += 1

        if straddling > max(2, len(lines) * 0.1):
            continue  
        if left_lines < 3 or right_lines < 3:
            continue  

        gap = max(
            (b - a for a, b in zip(xs, xs[1:]) if abs((a + b) / 2 - gutter) < 0.01),
            default=0,
        )
        if gap >= best_gap:
            best_gap = gap
            best_gutter = gutter

    return best_gutter


def _group_words_into_lines(words: list) -> list:
    rows: dict[int, list] = {}
    for w in words:
        key = round(w["top"] / 3)
        rows.setdefault(key, []).append(w)
    return list(rows.values())


def _words_to_text(words: list) -> str:
    if not words:
        return ""
    rows: dict[int, list] = {}
    for w in words:
        key = round(w["top"] / 3)
        rows.setdefault(key, []).append(w)

    lines = []
    for key in sorted(rows):
        row = sorted(rows[key], key=lambda w: w["x0"])
        lines.append(" ".join(w["text"] for w in row))
    return "\n".join(lines)


def _extract_docx_text(contents: bytes) -> str:
    doc = Document(io.BytesIO(contents))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


# Structured data extraction
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

_PHONE_PATTERN = re.compile(
    r"(\+?6?0?1[0-9][-.\s]*\d{3,4}[-.\s]*\d{4}|\+\d{1,3}[-.\s]*\d{2,4}[-.\s]*\d{3,4}[-.\s]*\d{3,4})"
)


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
    text_lower = text.lower()
    found = []
    for skill in SKILLS_VOCABULARY:
        # Word-boundary match so "R" doesn't match inside "Marketing", etc.
        pattern = r"\b" + re.escape(skill.lower()) + r"\b"
        if re.search(pattern, text_lower):
            found.append(skill)
    return found



_EXPERIENCE_HEADERS = {
    "experience", "work experience", "employment history",
    "professional experience", "career history", "work history",
}
_EDUCATION_HEADERS = {
    "education", "academic background", "educational background",
    "academic qualifications", "qualifications",
}
_SUMMARY_HEADERS = {
    "summary", "objective", "profile", "personal profile",
    "career objective", "professional summary", "about me", "bio",
}
_ALL_SECTION_HEADERS = _EXPERIENCE_HEADERS | _EDUCATION_HEADERS | _SUMMARY_HEADERS | {
    "skills", "technical skills", "projects",
    "certifications", "references", "achievements", "languages",
    "interests", "publications", "contact", "personal details",
}

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*"
_YEAR = r"(?:19|20)\d{2}"
_DATE_TOKEN = rf"(?:{_MONTH}{_YEAR}|{_YEAR})"
_DATE_RANGE_PATTERN = re.compile(
    rf"({_DATE_TOKEN})\s*(?:[-–—]|to)\s*({_DATE_TOKEN}|Present|Current|Now)",
    re.IGNORECASE,
)

_MONTH_ABBREVIATIONS = {
    "january": "Jan", "jan": "Jan",
    "february": "Feb", "feb": "Feb",
    "march": "Mar", "mar": "Mar",
    "april": "Apr", "apr": "Apr",
    "may": "May",
    "june": "Jun", "jun": "Jun",
    "july": "Jul", "jul": "Jul",
    "august": "Aug", "aug": "Aug",
    "september": "Sep", "sep": "Sep", "sept": "Sep",
    "october": "Oct", "oct": "Oct",
    "november": "Nov", "nov": "Nov",
    "december": "Dec", "dec": "Dec",
}
_PARSED_DATE_PATTERN = re.compile(
    rf"^(?P<month>{_MONTH})?(?P<year>{_YEAR})$", re.IGNORECASE
)


def _normalize_date(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    match = _PARSED_DATE_PATTERN.match(raw)
    if not match:
        return ""
    year = match.group("year")
    month_raw = (match.group("month") or "").strip().rstrip(".").lower()
    if not month_raw:
        return year
    abbrev = _MONTH_ABBREVIATIONS.get(month_raw)
    return f"{abbrev} {year}" if abbrev else year

_DEGREE_KEYWORDS = [
    "Bachelor", "Master", "PhD", "Doctorate", "Diploma", "Associate",
    "B.Sc", "BSc", "M.Sc", "MSc", "B.Eng", "BEng", "M.Eng", "MEng",
    "B.A.", "BA", "M.A.", "MA", "MBA", "Foundation", "Certificate",
]
_INSTITUTION_KEYWORDS = [
    "University", "Universiti", "College", "Institute", "Politeknik",
    "Polytechnic", "School",
]

_DEGREE_LEVEL_MAP = {
    "bachelor": "Bachelor's Degree", "b.sc": "Bachelor's Degree",
    "bsc": "Bachelor's Degree", "b.eng": "Bachelor's Degree",
    "beng": "Bachelor's Degree", "b.a.": "Bachelor's Degree",
    "ba": "Bachelor's Degree",
    "master": "Master's Degree", "m.sc": "Master's Degree",
    "msc": "Master's Degree", "m.eng": "Master's Degree",
    "meng": "Master's Degree", "m.a.": "Master's Degree",
    "ma": "Master's Degree", "mba": "Master's Degree",
    "phd": "PhD / Doctorate", "doctorate": "PhD / Doctorate",
    "diploma": "Diploma", "associate": "Diploma",
    "foundation": "STPM / A-Level / Foundation",
    "certificate": "Certificate",
}


def _normalize_degree(raw_keyword: str) -> str:
    if not raw_keyword:
        return ""
    mapped = _DEGREE_LEVEL_MAP.get(raw_keyword.strip().lower(), "")
    return mapped if mapped in EDUCATION_LEVELS else ""


def _normalize_field_of_study(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""

    close = difflib.get_close_matches(raw, FIELDS_OF_STUDY, n=1, cutoff=0.6)
    if close:
        return close[0]

    raw_lower = raw.lower()
    for option in FIELDS_OF_STUDY:
        if option.lower() in raw_lower or raw_lower in option.lower():
            return option
    return ""


def _split_into_sections(text: str) -> dict[str, str]:
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
            elif normalized in _SUMMARY_HEADERS:
                current_section = "summary"
            else:
                current_section = None  # a recognized-but-uninteresting header (e.g. "Skills")
            sections.setdefault(current_section, []) if current_section else None
            continue

        if current_section:
            sections.setdefault(current_section, []).append(line)

    return {name: "\n".join(lines) for name, lines in sections.items()}


def _looks_like_entry_header(line: str) -> bool:
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
    start_date = _normalize_date(start_date)
    end_date = _normalize_date(end_date)

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
    start_date = _normalize_date(start_date)
    end_date = _normalize_date(end_date)

    institution = next(
        (l.strip() for l in lines if any(kw.lower() in l.lower() for kw in _INSTITUTION_KEYWORDS)),
        "",
    )
    degree_keyword = next(
        (kw for kw in _DEGREE_KEYWORDS if re.search(rf"\b{re.escape(kw)}\b", full_text, re.IGNORECASE)),
        "",
    )
    degree = _normalize_degree(degree_keyword)
    field_of_study = ""
    field_match = re.search(r"\bin\s+([A-Z][A-Za-z\s]{2,40})", full_text)
    if field_match:
        field_of_study = _normalize_field_of_study(field_match.group(1).strip())

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


def _extract_bio(text: str) -> str:
    sections = _split_into_sections(text)
    block = sections.get("summary", "")
    if not block:
        return ""
    collapsed = " ".join(line.strip() for line in block.splitlines() if line.strip())
    max_len = 500
    if len(collapsed) > max_len:
        collapsed = collapsed[:max_len].rsplit(" ", 1)[0] + "..."
    return collapsed


@dataclass
class ParsedResume:
    full_name: str = ""
    email: str = ""
    phone: str = ""
    bio: str = ""
    skills: list[str] = field(default_factory=list)
    experience: list[dict] = field(default_factory=list)
    education: list[dict] = field(default_factory=list)
    raw_text_extracted: bool = False  

def parse_resume(contents: bytes, extension: str) -> ParsedResume:
    text = extract_text(contents, extension)
    if not text.strip():
        return ParsedResume(raw_text_extracted=False)

    return ParsedResume(
        full_name=_guess_name(text),
        email=_extract_email(text),
        phone=_extract_phone(text),
        bio=_extract_bio(text),
        skills=_extract_skills(text),
        experience=_extract_experience(text),
        education=_extract_education(text),
        raw_text_extracted=True,
    )