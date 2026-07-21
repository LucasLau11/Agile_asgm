from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from job_portal.database import get_db
from job_portal.models import Conversation, Message, Notification, SeekerProfile
from job_portal.routes.applications import EMPLOYER_DIRECTORY
from job_portal.schemas import ConversationOut, MessageCreate, MessageOut

router = APIRouter(tags=["Messaging"])

_MAX_PREVIEW_LEN = 80


def _seeker_name(seeker_id: int, db: Session) -> str:
    profile = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == seeker_id).first()
    if profile and profile.full_name:
        return profile.full_name
    return f"Seeker #{seeker_id}"


def _employer_name(employer_id: int) -> str:
    return EMPLOYER_DIRECTORY.get(employer_id, f"Employer #{employer_id}")


def _other_party_name(role: str, other_id: int, db: Session) -> str:
    """role is the *other* party's role (i.e. the opposite of the requester)."""
    if role == "seeker":
        return _seeker_name(other_id, db)
    return _employer_name(other_id)


def _preview(body: str) -> str:
    body = (body or "").strip().replace("\n", " ")
    if len(body) <= _MAX_PREVIEW_LEN:
        return body
    return body[: _MAX_PREVIEW_LEN - 1].rstrip() + "…"


def _get_or_create_conversation(
    db: Session, seeker_id: int, employer_id: int
) -> Conversation:
    convo = (
        db.query(Conversation)
        .filter(Conversation.seeker_id == seeker_id, Conversation.employer_id == employer_id)
        .first()
    )
    if convo:
        return convo
    convo = Conversation(seeker_id=seeker_id, employer_id=employer_id)
    db.add(convo)
    db.flush()  # assigns convo.id without committing yet
    return convo


@router.post("/api/messages")
async def api_send_message(body: MessageCreate, db: Session = Depends(get_db)):
    """US-40 / US-41: send a message. Creates the (seeker, employer)
    conversation on first contact, appends the message, and notifies the
    recipient — but never the sender (no self-notification on send)."""

    if body.sender_role == "seeker":
        seeker_id, employer_id = body.sender_id, body.recipient_id
    else:
        seeker_id, employer_id = body.recipient_id, body.sender_id

    convo = _get_or_create_conversation(db, seeker_id, employer_id)

    message = Message(
        conversation_id=convo.id,
        sender_role=body.sender_role,
        sender_id=body.sender_id,
        body=body.body,
        job_id=body.job_id,
    )
    db.add(message)
    convo.last_message_at = datetime.utcnow()

    sender_name = (
        _seeker_name(body.sender_id, db)
        if body.sender_role == "seeker"
        else _employer_name(body.sender_id)
    )
    recipient_role = "employer" if body.sender_role == "seeker" else "seeker"
    notif = Notification(
        seeker_id=body.recipient_id if recipient_role == "seeker" else None,
        employer_id=body.recipient_id if recipient_role == "employer" else None,
        title=f"New message from {sender_name}",
        message=_preview(body.body),
    )
    db.add(notif)

    db.commit()
    db.refresh(message)

    return JSONResponse(content=MessageOut.from_message(message).model_dump(mode="json"))


@router.get("/api/conversations")
async def api_list_conversations(
    role: str = Query(..., pattern="^(seeker|employer)$"),
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """US-42 / US-43: the inbox — one row per contact, most recently
    active conversation first, like a WhatsApp chat list."""

    query = db.query(Conversation)
    if role == "seeker":
        query = query.filter(Conversation.seeker_id == user_id)
    else:
        query = query.filter(Conversation.employer_id == user_id)
    conversations = query.order_by(Conversation.last_message_at.desc()).all()

    results = []
    for convo in conversations:
        other_id = convo.employer_id if role == "seeker" else convo.seeker_id
        other_role = "employer" if role == "seeker" else "seeker"
        last_msg = convo.messages[-1] if convo.messages else None
        unread_count = sum(
            1
            for m in convo.messages
            if not m.is_read and m.sender_role != role
        )
        results.append(
            ConversationOut(
                id=convo.id,
                other_party_id=other_id,
                other_party_name=_other_party_name(other_role, other_id, db),
                last_message_preview=_preview(last_msg.body) if last_msg else "",
                last_message_at=convo.last_message_at,
                unread_count=unread_count,
            ).model_dump(mode="json")
        )

    return JSONResponse(content=results)


@router.get("/api/conversations/{conversation_id}/messages")
async def api_get_conversation_messages(
    conversation_id: int,
    role: str = Query(..., pattern="^(seeker|employer)$"),
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Full thread history. Marks the other party's messages as read —
    opening a thread is what clears its unread count, same as any chat app."""

    convo = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    owner_id = convo.seeker_id if role == "seeker" else convo.employer_id
    if owner_id != user_id:
        raise HTTPException(status_code=403, detail="Not a participant in this conversation.")

    changed = False
    for m in convo.messages:
        if m.sender_role != role and not m.is_read:
            m.is_read = 1
            changed = True
    if changed:
        db.commit()

    other_id = convo.employer_id if role == "seeker" else convo.seeker_id
    other_role = "employer" if role == "seeker" else "seeker"

    return JSONResponse(
        content={
            "conversation_id": convo.id,
            "other_party_id": other_id,
            "other_party_name": _other_party_name(other_role, other_id, db),
            "messages": [
                MessageOut.from_message(m).model_dump(mode="json") for m in convo.messages
            ],
        }
    )


@router.post("/api/conversations/find-or-create")
async def api_find_or_create_conversation(
    role: str = Query(..., pattern="^(seeker|employer)$"),
    user_id: int = Query(...),
    other_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Used by the contextual 'Message Employer' / 'Message Seeker' buttons
    on job_detail.html / applicant_detail.html to jump straight into an
    (existing or brand new, still-empty) thread without posting a message
    first."""

    if role == "seeker":
        seeker_id, employer_id = user_id, other_id
    else:
        seeker_id, employer_id = other_id, user_id

    convo = _get_or_create_conversation(db, seeker_id, employer_id)
    db.commit()

    return JSONResponse(content={"conversation_id": convo.id})