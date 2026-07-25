"""
Skill-matching helpers shared between:
  - GET /api/jobs/recommended (existing — powers "Recommended for you")
  - GET /api/jobs/{job_id}    (US-24/US-25 — powers the job detail page's
                                missing-skills list and compatibility score)

This is a refactor of what used to be a private `_match_percentage()`
helper living only in seeker.py's recommended-jobs endpoint — pulled out
here so the single-job view can reuse the exact same algorithm instead of
a second, potentially-drifting copy of it.
"""

from typing import Dict, List


def compute_skill_match(seeker_skills: List[str], job_skills: List[str]) -> Dict:
    """
    Simple overlap-based matching algorithm.

    match_percentage = (number of the job's required skills the seeker has)
                        / (total number of the job's DISTINCT required skills) * 100

    matched_skills / missing_skills preserve the job posting's original
    casing and order (e.g. "SQL" not "sql") for display, even though the
    comparison itself is case-insensitive — de-duplicated the same way the
    percentage math is, so a job listing "Python, python" twice doesn't
    inflate or skew either the score or the displayed lists.
    """
    seeker_set = {s.strip().lower() for s in seeker_skills if s.strip()}
    job_set = {s.strip().lower() for s in job_skills if s.strip()}

    if not job_set or not seeker_set:
        percentage = 0
    else:
        overlap = seeker_set & job_set
        percentage = round(len(overlap) / len(job_set) * 100)

    seen = set()
    matched: List[str] = []
    missing: List[str] = []
    for skill in job_skills:
        cleaned = skill.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        (matched if key in seeker_set else missing).append(cleaned)

    return {
        "match_percentage": percentage,
        "matched_skills": matched,
        "missing_skills": missing,
    }