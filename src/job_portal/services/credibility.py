from sqlalchemy.orm import Session

from job_portal.models import Job

# Employer track record is bucketed by total job postings. Tuned so a
# single first-time posting doesn't score 0, but repeat employers are
# clearly rewarded. Adjust these thresholds as real usage data comes in.
_TRACK_RECORD_BUCKETS = [
    (1, 10),   # 1 posting total  -> 10/35 pts
    (2, 20),   # 2 postings       -> 20/35 pts
    (4, 28),   # 3-4 postings     -> 28/35 pts
    (999999, 35),  # 5+ postings  -> full 35 pts
]

_MAX_SANE_POSITIONS = 50  # postings asking for more than this look spammy/scammy


def _completeness_score(job: Job) -> int:
    score = 0
    if job.description and len(job.description.strip()) > 50:
        score += 15
    if job.location and job.location.strip():
        score += 10
    if job.skills_list():
        score += 10
    if job.salary_min is not None or job.salary_max is not None:
        score += 5
    return score


def _salary_sanity_score(job: Job) -> int:
    lo, hi = job.salary_min, job.salary_max
    if lo is None and hi is None:
        return 0
    if lo is not None and lo <= 0:
        return 0
    if hi is not None and hi <= 0:
        return 0
    if lo is not None and hi is not None and lo > hi:
        return 0
    return 15


def _positions_sanity_score(job: Job) -> int:
    available = job.positions_available or 0
    if 1 <= available <= _MAX_SANE_POSITIONS:
        return 10
    return 0


def _track_record_score(job: Job, db: Session) -> int:
    total_postings = (
        db.query(Job).filter(Job.employer_id == job.employer_id).count()
    )
    for threshold, pts in _TRACK_RECORD_BUCKETS:
        if total_postings <= threshold:
            return pts
    return _TRACK_RECORD_BUCKETS[-1][1]


def compute_credibility_reasons(job: Job, db: Session) -> list:
    """
    Human-readable explanation of what's shaping the credibility score —
    powers a tooltip on the trust seal, so the number isn't just an
    unexplained percentage. Mirrors the same conditions each sub-score
    function above checks.
    """
    reasons = []
    if not (job.description and len(job.description.strip()) > 50):
        reasons.append("Description is short or missing detail")
    if not (job.location and job.location.strip()):
        reasons.append("Location not specified")
    if not job.skills_list():
        reasons.append("No required skills listed")
    if job.salary_min is None and job.salary_max is None:
        reasons.append("Salary not specified")
    elif _salary_sanity_score(job) == 0:
        reasons.append("Salary range looks invalid")
    if not (1 <= (job.positions_available or 0) <= _MAX_SANE_POSITIONS):
        reasons.append("Unusual number of positions requested")
    total_postings = db.query(Job).filter(Job.employer_id == job.employer_id).count()
    if total_postings <= 2:
        reasons.append("New or limited-history employer")
    return reasons

def compute_credibility_score(job: Job, db: Session) -> int:
    score = (
        _completeness_score(job)
        + _salary_sanity_score(job)
        + _positions_sanity_score(job)
        + _track_record_score(job, db)
    )
    return max(0, min(score, 100))