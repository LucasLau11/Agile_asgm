"""Admin moderation (US-07/08/09): list, suspend/unsuspend, and delete
seeker and employer accounts. Every endpoint requires a real admin session
— the actor's identity comes only from require_role("admin", ...); the
*target* account id is a legitimate path param here, since moderation is
inherently "act on another account by id"."""

import os
import mimetypes
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from job_portal.database import get_db
from job_portal.models import Application, Employer, Job, SeekerProfile
from job_portal.routes.auth import require_role
from job_portal.schemas import AdminEmployerOut, AdminSeekerOut, AdminStatisticsOut, EmployerVerificationDecisionIn
from job_portal.services.account_deletion import delete_employer_account, delete_seeker_account
from job_portal.services.auth import delete_sessions_for_account

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _get_seeker_or_404(db: Session, seeker_id: int) -> SeekerProfile:
    seeker = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == seeker_id).first()
    if seeker is None:
        raise HTTPException(status_code=404, detail="Seeker account not found.")
    return seeker


def _get_employer_or_404(db: Session, employer_id: int) -> Employer:
    employer = db.query(Employer).filter(Employer.id == employer_id).first()
    if employer is None:
        raise HTTPException(status_code=404, detail="Employer account not found.")
    return employer


@router.get("/seekers", response_model=List[AdminSeekerOut])
def list_seekers(
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> List[AdminSeekerOut]:
    seekers = db.query(SeekerProfile).order_by(SeekerProfile.seeker_id).all()
    return [AdminSeekerOut.model_validate(s) for s in seekers]


@router.get("/employers", response_model=List[AdminEmployerOut])
def list_employers(
    search: Optional[str] = Query(None, max_length=150),
    verification_status: Optional[str] = Query(None, pattern="^(pending|approved|rejected)$"),
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> List[AdminEmployerOut]:
    query = db.query(Employer)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            Employer.company_name.ilike(term) | Employer.email.ilike(term) |
            Employer.registration_number.ilike(term)
        )
    if verification_status:
        query = query.filter(Employer.verification_status == verification_status)
    employers = query.order_by(Employer.id).all()
    return [AdminEmployerOut.model_validate(e) for e in employers]


@router.get("/employers/pending", response_model=List[AdminEmployerOut])
def list_pending_employers(
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> List[AdminEmployerOut]:
    return [AdminEmployerOut.model_validate(e) for e in db.query(Employer).filter(
        Employer.verification_status == "pending"
    ).order_by(Employer.verification_submitted_at.asc()).all()]


@router.get("/employers/{employer_id}", response_model=AdminEmployerOut)
def get_employer_detail(
    employer_id: int,
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> AdminEmployerOut:
    return AdminEmployerOut.model_validate(_get_employer_or_404(db, employer_id))


@router.get("/employers/{employer_id}/verification-document")
def get_verification_document(
    employer_id: int,
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
):
    employer = _get_employer_or_404(db, employer_id)
    path = employer.verification_document_path
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Verification document not found.")
    display_name = employer.verification_document_filename or "verification-document"
    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    # FileResponse's filename argument forces Content-Disposition: attachment,
    # which opens the OS download/file explorer instead of the browser viewer.
    # PDFs can be reviewed inline; DOCX remains a download because browsers do
    # not have a native Word-document renderer.
    disposition = "inline" if media_type == "application/pdf" else "attachment"
    safe_name = display_name.replace('"', "").replace("\r", "").replace("\n", "")
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}"'},
    )


@router.post("/employers/{employer_id}/approve", response_model=AdminEmployerOut)
def approve_employer(
    employer_id: int,
    admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> AdminEmployerOut:
    employer = _get_employer_or_404(db, employer_id)
    if not employer.verification_document_path:
        raise HTTPException(status_code=400, detail="Employer has not submitted a verification document.")
    employer.verification_status = "approved"
    employer.verified_at = datetime.utcnow()
    employer.verified_by_admin_id = admin_id
    employer.rejection_reason = None
    db.commit(); db.refresh(employer)
    return AdminEmployerOut.model_validate(employer)


@router.post("/employers/{employer_id}/reject", response_model=AdminEmployerOut)
def reject_employer(
    employer_id: int,
    payload: EmployerVerificationDecisionIn = Body(...),
    admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> AdminEmployerOut:
    if not payload.reason or not payload.reason.strip():
        raise HTTPException(status_code=422, detail="A rejection reason is required.")
    employer = _get_employer_or_404(db, employer_id)
    employer.verification_status = "rejected"
    employer.verified_at = datetime.utcnow()
    employer.verified_by_admin_id = admin_id
    employer.rejection_reason = payload.reason.strip()
    delete_sessions_for_account(db, "employer", employer_id)
    db.commit(); db.refresh(employer)
    return AdminEmployerOut.model_validate(employer)


@router.get("/statistics", response_model=AdminStatisticsOut)
def platform_statistics(
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> AdminStatisticsOut:
    return AdminStatisticsOut(
        seekers=db.query(SeekerProfile).count(), employers=db.query(Employer).count(),
        jobs=db.query(Job).count(), open_jobs=db.query(Job).filter(Job.status == "open").count(),
        applications=db.query(Application).count(),
        pending_verifications=db.query(Employer).filter(Employer.verification_status == "pending").count(),
        verified_employers=db.query(Employer).filter(Employer.verification_status == "approved").count(),
    )


@router.delete("/seekers/{seeker_id}", status_code=204)
def delete_seeker(
    seeker_id: int,
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> None:
    """US-07. Sessions are invalidated BEFORE the destructive commit (not
    after) — if invalidation ever failed, we'd rather fail loudly before
    deleting anything than leave a deleted account reachable via a stale
    cookie (see IMPORTANT 3 in the final review). Because seeker_id gets
    REISSUED to the next registrant (next_seeker_id = max + 1 in
    register_seeker), every row that references this id must be genuinely
    deleted, not orphaned — an orphaned row would silently become the next
    registrant's data (see CRITICAL 2 in the final review). This also
    deletes the resume file from disk (IMPORTANT 2) — leaving it behind
    would keep the most PII-dense artifact in the system reachable via the
    unauthenticated /uploads mount.
    WorkExperience/Education rows cascade-delete separately via the ORM
    relationship on SeekerProfile. Cascade logic lives in
    services/account_deletion.py, shared with the self-service delete
    endpoint (US-71) in routes/auth.py."""
    seeker = _get_seeker_or_404(db, seeker_id)
    delete_seeker_account(db, seeker)


@router.delete("/employers/{employer_id}", status_code=204)
def delete_employer(
    employer_id: int,
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> None:
    """US-08. Same reasoning as delete_seeker: sessions invalidated first,
    and every row referencing this employer_id is genuinely deleted rather
    than orphaned, since employer ids get reissued (SQLite rowid reuse on
    this INTEGER PRIMARY KEY). This includes the employer's own job
    postings — leaving them live would keep advertising a removed company
    on the public board, and orphaning them would hand them to whichever
    employer registers next and reuses this id. Cascade logic lives in
    services/account_deletion.py."""
    employer = _get_employer_or_404(db, employer_id)
    delete_employer_account(db, employer)


@router.post("/seekers/{seeker_id}/suspend", response_model=AdminSeekerOut)
def suspend_seeker(
    seeker_id: int,
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> AdminSeekerOut:
    """US-09. Sessions invalidated before the status commit, not after."""
    seeker = _get_seeker_or_404(db, seeker_id)
    delete_sessions_for_account(db, "seeker", seeker_id)
    seeker.status = "suspended"
    db.commit()
    db.refresh(seeker)
    return AdminSeekerOut.model_validate(seeker)


@router.post("/seekers/{seeker_id}/unsuspend", response_model=AdminSeekerOut)
def unsuspend_seeker(
    seeker_id: int,
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> AdminSeekerOut:
    seeker = _get_seeker_or_404(db, seeker_id)
    seeker.status = "active"
    db.commit()
    db.refresh(seeker)
    return AdminSeekerOut.model_validate(seeker)


@router.post("/employers/{employer_id}/suspend", response_model=AdminEmployerOut)
def suspend_employer(
    employer_id: int,
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> AdminEmployerOut:
    """Symmetric extension of US-09 to employers — Employer.status already
    exists and login() already enforces it (sub-project 1), unused until
    now. Building seeker-only suspend would leave that column/check dead
    for employers with no real savings. Sessions invalidated before the
    status commit, not after."""
    employer = _get_employer_or_404(db, employer_id)
    delete_sessions_for_account(db, "employer", employer_id)
    employer.status = "suspended"
    db.commit()
    db.refresh(employer)
    return AdminEmployerOut.model_validate(employer)


@router.post("/employers/{employer_id}/unsuspend", response_model=AdminEmployerOut)
def unsuspend_employer(
    employer_id: int,
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> AdminEmployerOut:
    employer = _get_employer_or_404(db, employer_id)
    employer.status = "active"
    db.commit()
    db.refresh(employer)
    return AdminEmployerOut.model_validate(employer)