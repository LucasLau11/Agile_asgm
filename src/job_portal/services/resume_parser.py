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

import difflib
import io
import re
from dataclasses import dataclass, field

import pdfplumber
from docx import Document

from job_portal.schemas import EDUCATION_LEVELS, FIELDS_OF_STUDY

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
            page_text = _extract_page_text(page)
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def _extract_page_text(page) -> str:
    """
    Many resume templates use a two-column layout (a narrow sidebar for
    contact/skills next to a wider main column for profile/education/
    experience). Plain page.extract_text() reads left-to-right in visual
    order, which INTERLEAVES the two columns line-by-line and garbles
    section headers (e.g. "EDUCATION" ends up merged into the middle of an
    unrelated sidebar address line) — this breaks section detection, and
    can even split a phone number's digits across two unrelated lines.

    To handle this, we look at word x-positions for a consistent vertical
    gap (a "gutter") splitting the page into two columns, and if found,
    extract each column as its own contiguous block of text (reading top
    to bottom within that column only) rather than one interleaved stream.
    Falls back to plain extract_text() for single-column resumes, or if
    anything about the layout looks ambiguous.
    """
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

    # The column with more words is treated as the "main" column (profile/
    # education/experience) and comes first, so section headers stay in
    # their natural top-to-bottom order for _split_into_sections.
    columns = sorted([left_words, right_words], key=len, reverse=True)
    return "\n".join(_words_to_text(col) for col in columns)


def _find_column_gutter(words: list, page_width: float) -> float | None:
    """
    Finds a vertical gutter that plausibly separates two real columns.

    A large x0 gap on its own isn't enough to prove a two-column layout —
    single-column resumes with short lines (e.g. "2019 - 2023") next to
    long ones can produce a wide gap between two words' x0 purely by
    coincidence, with no actual column structure. The real signal for a
    genuine column boundary is that NO line of text straddles it — every
    line's words fall entirely on one side or the other — because unlike
    a coincidental gap, a real gutter is where the page is physically
    split, so ordinary sentences never cross it. We also require several
    distinct lines on each side, so we don't split on a one-off short line.
    """
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
            continue  # too many lines cross this x — not a real gutter
        if left_lines < 3 or right_lines < 3:
            continue  # not enough independent lines on one side to call it a column

        # Prefer the widest underlying gap among valid candidates.
        gap = max(
            (b - a for a, b in zip(xs, xs[1:]) if abs((a + b) / 2 - gutter) < 0.01),
            default=0,
        )
        if gap >= best_gap:
            best_gap = gap
            best_gutter = gutter

    return best_gutter


def _group_words_into_lines(words: list) -> list:
    """Buckets words into visual lines by rounded vertical position."""
    rows: dict[int, list] = {}
    for w in words:
        key = round(w["top"] / 3)
        rows.setdefault(key, []).append(w)
    return list(rows.values())


def _words_to_text(words: list) -> str:
    """
    Reconstructs reading-order text from a list of pdfplumber words,
    grouping words into lines by vertical position (words with a close
    "top" are treated as the same line) and ordering left-to-right
    within each line.
    """
    if not words:
        return ""
    rows: dict[int, list] = {}
    for w in words:
        # Bucket by top position (rounded) so words on the same visual
        # line — even with tiny sub-pixel offsets — end up grouped together.
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


# ---------------------------------------------------------------------------
# Structured data extraction
# ---------------------------------------------------------------------------

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Covers common Malaysian formats (012-345 6789, +60123456789, and
# spaced-out variants like "+6017 - 362 7822") and generic international
# formats loosely. Separators use `*` (not `?`) because some templates put
# a full " - " (space-dash-space) between groups rather than a single
# character. Deliberately permissive — a false-positive "phone number" the
# user can just delete is much better than missing a real one because the
# regex was too strict.
_PHONE_PATTERN = re.compile(
    r"(\+?6?0?1[0-9][-.\s]*\d{3,4}[-.\s]*\d{4}|\+\d{1,3}[-.\s]*\d{2,4}[-.\s]*\d{3,4}[-.\s]*\d{3,4})"
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
_SUMMARY_HEADERS = {
    "summary", "objective", "profile", "personal profile",
    "career objective", "professional summary", "about me", "bio",
}
# Any of these appearing as their own line marks the END of whatever
# section came before it (used so we know where Experience/Education stop).
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

# Maps every month spelling _MONTH can match (full names, abbreviations,
# any casing) to the 3-letter form the frontend's month/year picker — and
# therefore the schema's date validator — requires (e.g. "Jan 2023").
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
    """
    Converts a date token extracted from resume text (which may be a full
    month name like "April", any casing, with/without a trailing period)
    into the "Mmm YYYY" format required by the schema's date validator —
    the same format the frontend's month/year picker produces. Falls back
    to an empty string (rather than passing through something the
    validator would reject) if the token doesn't parse as expected.
    """
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

# The profile's "education level" and "field of study" are fixed-option
# dropdowns (see schemas.EDUCATION_LEVELS / FIELDS_OF_STUDY) — free text
# from a resume, even when we're confident we found the right concept
# (e.g. "Bachelor", "Software Eengineering" with a typo), will fail
# validation unless it's normalized to one of those exact strings. Blank
# is always a valid fallback (the field validators only reject non-blank
# values that aren't in the list), so when we can't confidently map
# something we return "" rather than risk sending an invalid value that
# blocks the whole "apply suggestions" action.
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
    """Maps a raw degree keyword (as found via _DEGREE_KEYWORDS) to the
    matching schemas.EDUCATION_LEVELS option, or "" if there's no
    confident mapping."""
    if not raw_keyword:
        return ""
    mapped = _DEGREE_LEVEL_MAP.get(raw_keyword.strip().lower(), "")
    return mapped if mapped in EDUCATION_LEVELS else ""


def _normalize_field_of_study(raw: str) -> str:
    """
    Maps free-text extracted from the resume (e.g. "Software Eengineering",
    typo and all) to the closest schemas.FIELDS_OF_STUDY option. Tries a
    fuzzy match first (handles typos/casing), then a loose substring match,
    and gives up to "" rather than guessing "Other" — a blank field the
    person can fill in themselves beats a wrong guess.
    """
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


def _extract_bio(text: str) -> str:
    """
    Pull a short bio/summary suggestion from a Summary/Objective/Profile
    section, if the resume has one. Collapsed to a single paragraph and
    capped in length so it's a reasonable "suggestion", not the whole block.
    """
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
        bio=_extract_bio(text),
        skills=_extract_skills(text),
        experience=_extract_experience(text),
        education=_extract_education(text),
        raw_text_extracted=True,
    )