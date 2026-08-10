"""Admin moderation (US-07/08/09): list, suspend/unsuspend, and delete
seeker and employer accounts. Every endpoint requires a real admin session
— the actor's identity comes only from require_role("admin", ...); the
*target* account id is a legitimate path param here, since moderation is
inherently "act on another account by id"."""

import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from job_portal.database import get_db
from job_portal.models import Application, Conversation, Employer, InterviewInvite, Job, Message, Notification, SeekerProfile
from job_portal.routes.auth import require_role
from job_portal.schemas import AdminEmployerOut, AdminSeekerOut
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
    _admin_id: int = Depends(require_role("admin", "Must be logged in as an administrator.")),
    db: Session = Depends(get_db),
) -> List[AdminEmployerOut]:
    employers = db.query(Employer).order_by(Employer.id).all()
    return [AdminEmployerOut.model_validate(e) for e in employers]


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
    relationship on SeekerProfile."""
    seeker = _get_seeker_or_404(db, seeker_id)
    delete_sessions_for_account(db, "seeker", seeker_id)

    if seeker.resume_url and os.path.exists(seeker.resume_url):
        os.remove(seeker.resume_url)

    db.query(Application).filter(Application.seeker_id == seeker_id).delete()
    db.query(Notification).filter(Notification.seeker_id == seeker_id).delete()

    conversation_ids = [
        c.id for c in db.query(Conversation).filter(Conversation.seeker_id == seeker_id).all()
    ]
    if conversation_ids:
        message_ids = [
            m_id for (m_id,) in db.query(Message.id)
            .filter(Message.conversation_id.in_(conversation_ids)).all()
        ]
        if message_ids:
            # Bulk .delete() below bypasses the ORM, so Message's
            # cascade="all, delete-orphan" relationship to InterviewInvite
            # never fires — delete these explicitly first, or the orphaned
            # InterviewInvite row survives keyed to a message_id SQLite
            # immediately reissues to the next unrelated message.
            db.query(InterviewInvite).filter(InterviewInvite.message_id.in_(message_ids)).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.seeker_id == seeker_id).delete()

    db.delete(seeker)
    db.commit()


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
    employer registers next and reuses this id."""
    employer = _get_employer_or_404(db, employer_id)
    delete_sessions_for_account(db, "employer", employer_id)

    job_ids = [j.id for j in db.query(Job).filter(Job.employer_id == employer_id).all()]
    if job_ids:
        db.query(Application).filter(Application.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(Job).filter(Job.employer_id == employer_id).delete()

    db.query(Notification).filter(Notification.employer_id == employer_id).delete()

    conversation_ids = [
        c.id for c in db.query(Conversation).filter(Conversation.employer_id == employer_id).all()
    ]
    if conversation_ids:
        message_ids = [
            m_id for (m_id,) in db.query(Message.id)
            .filter(Message.conversation_id.in_(conversation_ids)).all()
        ]
        if message_ids:
            # Bulk .delete() below bypasses the ORM, so Message's
            # cascade="all, delete-orphan" relationship to InterviewInvite
            # never fires — delete these explicitly first, or the orphaned
            # InterviewInvite row survives keyed to a message_id SQLite
            # immediately reissues to the next unrelated message.
            db.query(InterviewInvite).filter(InterviewInvite.message_id.in_(message_ids)).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.employer_id == employer_id).delete()

    db.delete(employer)
    db.commit()


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
