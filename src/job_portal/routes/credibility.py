"""
US-11: Job posting credibility score.

Replaces the temporary `_placeholder_score()` that lived in
job_portal/routers/seeker.py. That placeholder gave every job a fixed
score based only on 4 yes/no checks on the job row itself (does it have
a location, a long-enough description, etc). It never varied with the
employer's actual track record, so a brand-new employer's very first
post scored identically to a repeat employer with a long history — not
a real signal of trustworthiness.

This version scores a job on two kinds of signal:

  1. Posting completeness/quality — does this specific posting look
     like a real, well-specified vacancy (has description, location,
     skills, a sane salary range, a sane number of open positions)?

  2. Employer track record — how many jobs has this employer_id posted
     in total? An employer with a longer posting history is a stronger
     trust signal than a one-off, brand-new employer_id. (We don't have
     an `employers` table with verification/age fields yet — this is
     the best proxy available from the current schema. If/when an
     Employer model is added, e.g. `is_verified`, `created_at`, that
     should be folded in here too.)

Usage:
    from job_portal.services.credibility import compute_credibility_score
    score = compute_credibility_score(job, db)
"""

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
        # No salary listed at all — neutral, not penalized twice
        # (already reflected in completeness above).
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


def compute_credibility_score(job: Job, db: Session) -> int:
    """
    Compute a 0-100 credibility score for a single job posting.

    Requires a live db session (unlike the old placeholder) because the
    employer track record component needs to look up how many other
    jobs this employer_id has posted.
    """
    score = (
        _completeness_score(job)
        + _salary_sanity_score(job)
        + _positions_sanity_score(job)
        + _track_record_score(job, db)
    )
    return max(0, min(score, 100))