import os
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from job_portal.database import get_db
from job_portal.models import Conversation, Message, Notification, SeekerProfile
from job_portal.routes.applications import EMPLOYER_DIRECTORY
from job_portal.schemas import ConversationOut, MessageCreate, MessageEdit, MessageOut
from job_portal.services.file_validation import (
    MAX_MESSAGE_ATTACHMENT_SIZE_BYTES,
    detect_safe_message_attachment,
    sanitize_display_filename,
)
from job_portal.services.message_crypto import decrypt_text, encrypt_text

router = APIRouter(tags=["Messaging"])

_MAX_PREVIEW_LEN = 80
EDIT_WINDOW_MINUTES = 15
ATTACHMENTS_DIR = "uploads/messages"


# ---------- Name / preview helpers ----------


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


def _truncate(text: str) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= _MAX_PREVIEW_LEN:
        return text
    return text[: _MAX_PREVIEW_LEN - 1].rstrip() + "…"


def _display_body(message: Message) -> str:
    """The plaintext to show for a message: decrypted body, or a fixed
    placeholder if it was deleted for everyone."""
    if message.is_deleted:
        return "This message was deleted"
    return decrypt_text(message.body)


def _preview_for(message: Message) -> str:
    body = _display_body(message)
    if not body and message.attachment_filename and not message.is_deleted:
        return f"📎 {message.attachment_filename}"
    return _truncate(body)


def _message_out(message: Message) -> dict:
    return MessageOut.from_message(message, body=_display_body(message)).model_dump(mode="json")


def _visible_messages(convo: Conversation, role: str) -> list[Message]:
    """Messages that haven't been 'deleted for me' by this role. 'Deleted
    for everyone' messages stay in this list — they're still visible, just
    rendered as a placeholder (see _display_body)."""
    col = "deleted_for_seeker" if role == "seeker" else "deleted_for_employer"
    return [m for m in convo.messages if not getattr(m, col)]


def _get_or_create_conversation(db: Session, seeker_id: int, employer_id: int) -> Conversation:
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


def _notify_recipient(
    db: Session, sender_role: str, sender_id: int, recipient_id: int, preview_text: str
) -> None:
    """Never notifies the sender — recipient only, same as any chat app."""
    sender_name = (
        _seeker_name(sender_id, db) if sender_role == "seeker" else _employer_name(sender_id)
    )
    recipient_role = "employer" if sender_role == "seeker" else "seeker"
    db.add(
        Notification(
            seeker_id=recipient_id if recipient_role == "seeker" else None,
            employer_id=recipient_id if recipient_role == "employer" else None,
            title=f"New message from {sender_name}",
            message=_truncate(preview_text) or "Sent an attachment",
        )
    )


def _require_participant(convo: Conversation, role: str, user_id: int) -> None:
    owner_id = convo.seeker_id if role == "seeker" else convo.employer_id
    if owner_id != user_id:
        raise HTTPException(status_code=403, detail="Not a participant in this conversation.")


# ---------- Send (text) ----------


@router.post("/api/messages")
async def api_send_message(body: MessageCreate, db: Session = Depends(get_db)):
    """US-40 / US-41: send a text message. Creates the (seeker, employer)
    conversation on first contact, appends the message, and notifies the
    recipient — but never the sender."""

    if body.sender_role == "seeker":
        seeker_id, employer_id = body.sender_id, body.recipient_id
    else:
        seeker_id, employer_id = body.recipient_id, body.sender_id

    convo = _get_or_create_conversation(db, seeker_id, employer_id)

    message = Message(
        conversation_id=convo.id,
        sender_role=body.sender_role,
        sender_id=body.sender_id,
        body=encrypt_text(body.body),
        job_id=body.job_id,
    )
    db.add(message)
    convo.last_message_at = datetime.utcnow()
    _notify_recipient(db, body.sender_role, body.sender_id, body.recipient_id, body.body)

    db.commit()
    db.refresh(message)

    return JSONResponse(content=_message_out(message))


# ---------- Send (with attachment) ----------


@router.post("/api/messages/attachment")
async def api_send_message_with_attachment(
    sender_role: str = Form(..., pattern="^(seeker|employer)$"),
    sender_id: int = Form(...),
    recipient_id: int = Form(...),
    body: str = Form(""),
    job_id: Optional[int] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Same as api_send_message, but attaches an image or document. The
    caption (`body`) is optional — a bare attachment is a valid message."""

    contents = await file.read()
    if len(contents) > MAX_MESSAGE_ATTACHMENT_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Attachment exceeds the 10 MB limit.")

    detected = detect_safe_message_attachment(contents)
    if not detected:
        raise HTTPException(
            status_code=422,
            detail="Unsupported file type. Allowed: JPG, PNG, GIF, WEBP, PDF, DOCX.",
        )
    extension, attachment_type = detected

    caption = (body or "").strip()
    if len(caption) > 4000:
        raise HTTPException(status_code=422, detail="Caption is too long (max 4000 characters).")

    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    disk_filename = f"{uuid4().hex}{extension}"
    disk_path = os.path.join(ATTACHMENTS_DIR, disk_filename)
    with open(disk_path, "wb") as fh:
        fh.write(contents)

    if sender_role == "seeker":
        seeker_id, employer_id = sender_id, recipient_id
    else:
        seeker_id, employer_id = recipient_id, sender_id
    convo = _get_or_create_conversation(db, seeker_id, employer_id)

    message = Message(
        conversation_id=convo.id,
        sender_role=sender_role,
        sender_id=sender_id,
        body=encrypt_text(caption),
        job_id=job_id,
        attachment_filename=sanitize_display_filename(file.filename),
        attachment_url=disk_path.replace("\\", "/"),
        attachment_type=attachment_type,
    )
    db.add(message)
    convo.last_message_at = datetime.utcnow()
    _notify_recipient(
        db, sender_role, sender_id, recipient_id, caption or f"📎 {message.attachment_filename}"
    )

    db.commit()
    db.refresh(message)

    return JSONResponse(content=_message_out(message))


# ---------- Edit ----------


@router.put("/api/messages/{message_id}")
async def api_edit_message(
    message_id: int,
    body: MessageEdit,
    role: str = Query(..., pattern="^(seeker|employer)$"),
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Sender-only, and only within EDIT_WINDOW_MINUTES of sending — matches
    the common "edit window" pattern in chat apps rather than open-ended
    editing, which would make read receipts/history misleading."""

    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found.")
    if message.sender_role != role or message.sender_id != user_id:
        raise HTTPException(status_code=403, detail="Only the sender can edit this message.")
    if message.is_deleted:
        raise HTTPException(status_code=400, detail="Can't edit a deleted message.")
    if datetime.utcnow() - message.created_at > timedelta(minutes=EDIT_WINDOW_MINUTES):
        raise HTTPException(
            status_code=400,
            detail=f"Messages can only be edited within {EDIT_WINDOW_MINUTES} minutes of sending.",
        )

    message.body = encrypt_text(body.body)
    message.edited_at = datetime.utcnow()
    db.commit()
    db.refresh(message)

    return JSONResponse(content=_message_out(message))


# ---------- Delete ----------


def _best_effort_delete_attachment(path: Optional[str]) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass  # not worth failing the delete request over a stray file


@router.delete("/api/messages/{message_id}")
async def api_delete_message(
    message_id: int,
    role: str = Query(..., pattern="^(seeker|employer)$"),
    user_id: int = Query(...),
    scope: str = Query("me", pattern="^(me|everyone)$"),
    db: Session = Depends(get_db),
):
    """scope=me: hides the message only in the requester's own view — the
    other party still sees it, unaffected.
    scope=everyone: sender-only; clears the content for both parties and
    marks it as deleted (shown as a placeholder, not removed from the
    thread entirely — same convention as WhatsApp/Telegram)."""

    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found.")

    _require_participant(message.conversation, role, user_id)

    if scope == "everyone":
        if message.sender_role != role or message.sender_id != user_id:
            raise HTTPException(
                status_code=403, detail="Only the sender can delete this message for everyone."
            )
        message.is_deleted = 1
        message.body = encrypt_text("")
        _best_effort_delete_attachment(message.attachment_url)
        message.attachment_filename = None
        message.attachment_url = None
        message.attachment_type = None
    else:
        col = "deleted_for_seeker" if role == "seeker" else "deleted_for_employer"
        setattr(message, col, 1)

    db.commit()
    return JSONResponse(content={"success": True})


# ---------- Inbox / thread ----------


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
        visible = _visible_messages(convo, role)
        last_msg = visible[-1] if visible else None
        unread_count = sum(1 for m in visible if not m.is_read and m.sender_role != role)
        results.append(
            ConversationOut(
                id=convo.id,
                other_party_id=other_id,
                other_party_name=_other_party_name(other_role, other_id, db),
                last_message_preview=_preview_for(last_msg) if last_msg else "",
                last_message_at=(last_msg.created_at if last_msg else convo.last_message_at),
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

    _require_participant(convo, role, user_id)

    visible = _visible_messages(convo, role)

    changed = False
    for m in visible:
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
            "messages": [_message_out(m) for m in visible],
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