"""
Shared account-deletion cascades, extracted from routes/admin.py so both
admin-initiated deletion (US-07/08) and self-service deletion (US-71) run
the exact same cleanup rather than maintaining two copies that could drift
out of sync.

Sessions are invalidated BEFORE the destructive commit (not after) — if
invalidation ever failed, we'd rather fail loudly before deleting anything
than leave a deleted account reachable via a stale cookie. Because
seeker_id/employer_id get REISSUED to the next registrant (see
next_seeker_id = max + 1 in routes/auth.py), every row referencing this id
must be genuinely deleted, not orphaned — an orphaned row would silently
become the next registrant's data.
"""

import os

from sqlalchemy.orm import Session

from job_portal.models import (
    Application,
    Conversation,
    Employer,
    InterviewInvite,
    Job,
    Message,
    Notification,
    SeekerProfile,
)
from job_portal.services.auth import delete_sessions_for_account


def delete_seeker_account(db: Session, seeker: SeekerProfile) -> None:
    """Deletes a seeker account and every row that references it. Also
    deletes the resume and profile picture files from disk — leaving them
    behind would keep PII reachable via the unauthenticated /uploads mount.
    WorkExperience/Education rows cascade-delete separately via the ORM
    relationship on SeekerProfile."""
    seeker_id = seeker.seeker_id
    delete_sessions_for_account(db, "seeker", seeker_id)

    if seeker.resume_url and os.path.exists(seeker.resume_url):
        os.remove(seeker.resume_url)
    if seeker.profile_picture_url and os.path.exists(seeker.profile_picture_url):
        os.remove(seeker.profile_picture_url)

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


def delete_employer_account(db: Session, employer: Employer) -> None:
    """Deletes an employer account and every row that references it,
    including the employer's own job postings — leaving them live would
    keep advertising a removed company on the public board, and orphaning
    them would hand them to whichever employer registers next and reuses
    this id."""
    employer_id = employer.id
    delete_sessions_for_account(db, "employer", employer_id)

    if employer.verification_document_path and os.path.exists(employer.verification_document_path):
        os.remove(employer.verification_document_path)

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
            db.query(InterviewInvite).filter(InterviewInvite.message_id.in_(message_ids)).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.employer_id == employer_id).delete()

    db.delete(employer)
    db.commit()