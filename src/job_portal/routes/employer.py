"""
Teammate A's routes: employer-side job posting management.

Covers:
  US-27  Create job postings
  US-28  View job postings (employer's own list, including drafts/closed)
  US-29  Update job postings
  US-30  Delete job postings
  US-31  Specify skill requirements when creating a job posting
  US-32  Update skill requirements

Every endpoint requires a real employer session via Depends(require_role("employer", ...)).
The employer_id is resolved from the session cookie and is never a client-suppliable value.

Status values on Job.status stay "draft" / "open" / "closed". See the note
at the top of the employer section in schemas.py for why "open" is kept
instead of "active" (short version: Teammate B's seeker-facing /api/jobs
filters on Job.status == "open", and changing that value out from under
them would silently break their endpoint).
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from job_portal.database import get_db
from job_portal.models import Application, Employer, Job, Notification
from job_portal.routes.auth import require_role
from job_portal.schemas import EmployerJobOut, JobCreate, JobUpdate
from job_portal.services.credibility import compute_credibility_score

router = APIRouter(prefix="/api/employer", tags=["employer-jobs"])


def _find_job_or_404(db: Session, employer_id: int, job_id: int) -> Job:
    job = (
        db.query(Job)
        .filter(Job.id == job_id, Job.employer_id == employer_id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job posting not found.")
    return job


def _check_duplicate_title(
    db: Session, employer_id: int, title: str, exclude_job_id: Optional[int] = None
) -> None:
    """
    Mirrors the frontend's duplicate-title guard — enforced here too because
    a client-side check is trivially bypassed (devtools, curl, Postman).
    Scoped per-employer: two different employers CAN post the same title
    (e.g. "Software Engineer" is a common title); only one employer can't
    have two of their own postings share a title.
    """
    query = db.query(Job).filter(
        Job.employer_id == employer_id,
        func.lower(Job.title) == title.lower(),
    )
    if exclude_job_id is not None:
        query = query.filter(Job.id != exclude_job_id)
    if query.first() is not None:
        raise HTTPException(
            status_code=409,
            detail="You already have a job posting with this title.",
        )


# ---------------------------------------------------------------------------
# US-28 — View own job postings (employer's management list)
# ---------------------------------------------------------------------------


@router.get("/jobs", response_model=List[EmployerJobOut])
def list_employer_jobs(
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
) -> List[EmployerJobOut]:
    """
    List every posting belonging to one employer — draft, open, AND closed
    (unlike Teammate B's GET /api/jobs, which only shows "open" postings
    to job seekers). Powers the search box + status filter on the job
    management page.
    """
    query = db.query(Job).filter(Job.employer_id == employer_id)

    if keyword:
        query = query.filter(Job.title.ilike(f"%{keyword}%"))

    if status and status != "all":
        query = query.filter(Job.status == status)

    jobs = query.order_by(Job.created_at.desc()).all()
    return [
        EmployerJobOut.from_job(job, credibility_score=compute_credibility_score(job, db))
        for job in jobs
    ]


@router.get("/jobs/{job_id}", response_model=EmployerJobOut)
def get_employer_job(
    job_id: int,
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
) -> EmployerJobOut:
    job = _find_job_or_404(db, employer_id, job_id)
    return EmployerJobOut.from_job(job, credibility_score=compute_credibility_score(job, db))


# ---------------------------------------------------------------------------
# US-27 / US-31 — Create a job posting (with required skills)
# ---------------------------------------------------------------------------


@router.post("/jobs", response_model=EmployerJobOut, status_code=201)
def create_job(
    payload: JobCreate,
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
) -> EmployerJobOut:
    _check_duplicate_title(db, employer_id, payload.title)

    job = Job(
        employer_id=employer_id,
        title=payload.title,
        description=payload.description,
        location=payload.location,
        state=payload.state,
        job_type=payload.job_type,
        salary_min=payload.salary_min,
        salary_max=payload.salary_max,
        skills_required=",".join(payload.skills_required),
        positions_available=payload.positions_available,
        status="draft",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return EmployerJobOut.from_job(job, credibility_score=compute_credibility_score(job, db))


# ---------------------------------------------------------------------------
# US-29 / US-32 — Update a job posting (including its skills)
# ---------------------------------------------------------------------------


@router.put("/jobs/{job_id}", response_model=EmployerJobOut)
def update_job(
    job_id: int,
    payload: JobUpdate,
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
) -> EmployerJobOut:
    job = _find_job_or_404(db, employer_id, job_id)
    _check_duplicate_title(db, employer_id, payload.title, exclude_job_id=job_id)

    job.title = payload.title
    job.description = payload.description
    job.location = payload.location
    job.state = payload.state
    job.job_type = payload.job_type
    job.salary_min = payload.salary_min
    job.salary_max = payload.salary_max
    job.skills_required = ",".join(payload.skills_required)
    job.positions_available = payload.positions_available

    db.commit()
    db.refresh(job)
    return EmployerJobOut.from_job(job, credibility_score=compute_credibility_score(job, db))


# ---------------------------------------------------------------------------
# Publish / close — status transitions (not full field updates)
# ---------------------------------------------------------------------------


@router.post("/jobs/{job_id}/publish", response_model=EmployerJobOut)
def publish_job(
    job_id: int,
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
) -> EmployerJobOut:
    """Draft -> open. Seekers can now see and apply to this posting."""
    job = _find_job_or_404(db, employer_id, job_id)
    employer = db.query(Employer).filter(Employer.id == employer_id).first()
    if not employer or employer.verification_status == "rejected" or (
        employer.verification_status == "pending" and employer.verification_document_path
    ):
        raise HTTPException(
            status_code=403,
            detail="Employer verification must be approved before publishing jobs.",
        )
    job.status = "open"
    db.commit()
    db.refresh(job)
    return EmployerJobOut.from_job(job, credibility_score=compute_credibility_score(job, db))


@router.post("/jobs/{job_id}/close", response_model=EmployerJobOut)
def close_job(
    job_id: int,
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
) -> EmployerJobOut:
    """Open -> closed. Stops accepting new applications."""
    job = _find_job_or_404(db, employer_id, job_id)
    job.status = "closed"
    db.commit()
    db.refresh(job)
    return EmployerJobOut.from_job(job, credibility_score=compute_credibility_score(job, db))


# ---------------------------------------------------------------------------
# US-30 — Delete a job posting
# ---------------------------------------------------------------------------


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(
    job_id: int,
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
) -> None:
    """
    Deletes a posting regardless of status (draft, open, or closed) — the
    frontend now shows Delete on drafts too, this just matches that on the
    backend.

    Application rows referencing this job_id are genuinely deleted, not
    orphaned — Job.id is a bare SQLite rowid and gets reissued to the next
    job created anywhere on the platform, so an orphaned Application would
    silently be re-adopted by a completely different employer's job. This
    is exploitable in practice: routes/applications.py's applicant-detail
    and stage-update endpoints join through Job.employer_id for ownership
    scoping, so a reused job id would hand the new owner the deleted
    applicant's name/email/cover letter and let them mutate the pipeline
    stage. Notification rows tied to those applications are cleaned up
    too. Mirrors routes/admin.py's delete_employer, which already applies
    this same reasoning to a deleted employer's jobs.
    """
    job = _find_job_or_404(db, employer_id, job_id)

    application_ids = [
        a.id for a in db.query(Application).filter(Application.job_id == job_id).all()
    ]
    if application_ids:
        db.query(Notification).filter(
            Notification.application_id.in_(application_ids)
        ).delete(synchronize_session=False)
        db.query(Application).filter(Application.job_id == job_id).delete(synchronize_session=False)

    db.delete(job)
    db.commit()
