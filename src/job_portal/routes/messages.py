import mimetypes
import os
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from job_portal.database import get_db
from job_portal.models import Conversation, InterviewInvite, Message, Notification, SeekerProfile
from job_portal.routes.applications import EMPLOYER_DIRECTORY
from job_portal.schemas import (
    ConversationOut,
    InterviewInviteCreate,
    InterviewResponseIn,
    MessageCreate,
    MessageEdit,
    MessageOut,
)
from job_portal.services.file_validation import (
    MAX_MESSAGE_ATTACHMENT_SIZE_BYTES,
    detect_safe_message_attachment,
    sanitize_display_filename,
)
from job_portal.services.message_crypto import decrypt_bytes, decrypt_text, encrypt_bytes, encrypt_text

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


def _visible_messages(convo: Conversation, role: str) -> list:
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


def _unhide_for_both(convo: Conversation) -> None:
    """A conversation someone had 'deleted' (hidden from their own inbox)
    reappears once there's fresh activity — same convention as WhatsApp:
    deleting a chat clears your view of it, it doesn't block the contact."""
    convo.hidden_for_seeker = 0
    convo.hidden_for_employer = 0


def _is_blocked(convo: Conversation) -> bool:
    return bool(convo.blocked_by_seeker or convo.blocked_by_employer)


def _require_unblocked(convo: Conversation) -> None:
    if _is_blocked(convo):
        raise HTTPException(
            status_code=403,
            detail="Messages are unavailable because this conversation has been blocked.",
        )


def _block_status(convo: Conversation, role: str) -> dict:
    blocked_by_me = (
        bool(convo.blocked_by_seeker) if role == "seeker" else bool(convo.blocked_by_employer)
    )
    return {"is_blocked": _is_blocked(convo), "blocked_by_me": blocked_by_me}


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
    _require_unblocked(convo)
    _unhide_for_both(convo)

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
    caption (`body`) is optional — a bare attachment is a valid message.
    The file is encrypted before it's written to disk (see
    services/message_crypto.py) and served back out through the decrypting
    GET /api/messages/{id}/attachment endpoint, never directly."""

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

    if sender_role == "seeker":
        seeker_id, employer_id = sender_id, recipient_id
    else:
        seeker_id, employer_id = recipient_id, sender_id
    convo = _get_or_create_conversation(db, seeker_id, employer_id)
    _require_unblocked(convo)
    _unhide_for_both(convo)

    message = Message(
        conversation_id=convo.id,
        sender_role=sender_role,
        sender_id=sender_id,
        body=encrypt_text(caption),
        job_id=job_id,
        attachment_filename=sanitize_display_filename(file.filename),
        attachment_type=attachment_type,
    )
    db.add(message)
    db.flush()  # need message.id before naming the file on disk

    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    disk_filename = f"{uuid4().hex}{extension}"
    disk_path = os.path.join(ATTACHMENTS_DIR, disk_filename)
    with open(disk_path, "wb") as fh:
        fh.write(encrypt_bytes(contents))
    message.attachment_url = disk_path.replace("\\", "/")

    convo.last_message_at = datetime.utcnow()
    _notify_recipient(
        db, sender_role, sender_id, recipient_id, caption or f"📎 {message.attachment_filename}"
    )

    db.commit()
    db.refresh(message)

    return JSONResponse(content=_message_out(message))


@router.get("/api/messages/{message_id}/attachment")
async def api_get_message_attachment(
    message_id: int,
    role: str = Query(..., pattern="^(seeker|employer)$"),
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Decrypts and serves an attachment. Not exposed via the static
    /uploads mount — that would serve raw ciphertext — so this is the only
    way to actually retrieve one, and it checks conversation membership
    the same way the message-list endpoint does."""

    message = db.query(Message).filter(Message.id == message_id).first()
    if not message or not message.attachment_url:
        raise HTTPException(status_code=404, detail="Attachment not found.")

    _require_participant(message.conversation, role, user_id)

    if not os.path.exists(message.attachment_url):
        raise HTTPException(status_code=404, detail="Attachment file is missing on the server.")

    with open(message.attachment_url, "rb") as fh:
        encrypted_contents = fh.read()
    try:
        plaintext_contents = decrypt_bytes(encrypted_contents)
    except Exception as exc:  # InvalidToken or similar
        raise HTTPException(status_code=500, detail="Could not decrypt attachment.") from exc

    media_type = mimetypes.guess_type(message.attachment_url)[0] or "application/octet-stream"
    filename = message.attachment_filename or "attachment"
    return Response(
        content=plaintext_contents,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


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


# ---------- Interview invitations (US-46 / US-47) ----------


@router.post("/api/messages/interview-invite")
async def api_send_interview_invite(
    employer_id: int = Query(...),
    seeker_id: int = Query(...),
    job_id: Optional[int] = Query(None),
    body: InterviewInviteCreate = Body(...),
    db: Session = Depends(get_db),
):
    """US-46: employer sends a structured interview invitation instead of
    plain text. Rendered as a distinct card in messages.html, with an
    Accept/Decline action for the seeker (see api_respond_to_interview)."""

    convo = _get_or_create_conversation(db, seeker_id, employer_id)
    _require_unblocked(convo)
    _unhide_for_both(convo)

    message = Message(
        conversation_id=convo.id,
        sender_role="employer",
        sender_id=employer_id,
        body=encrypt_text(""),  # scheduling details live on InterviewInvite, not body
        job_id=job_id,
        message_type="interview_invite",
    )
    db.add(message)
    db.flush()  # need message.id before creating the linked invite row

    invite = InterviewInvite(
        message_id=message.id,
        scheduled_at=body.scheduled_at,
        duration_minutes=body.duration_minutes,
        mode=body.mode,
        location_or_link=body.location_or_link or "",
        notes=body.notes or "",
    )
    db.add(invite)

    convo.last_message_at = datetime.utcnow()
    _notify_recipient(
        db,
        "employer",
        employer_id,
        seeker_id,
        f"Interview invitation for {body.scheduled_at.strftime('%d %b, %I:%M %p')}",
    )

    db.commit()
    db.refresh(message)

    return JSONResponse(content=_message_out(message))


@router.post("/api/messages/{message_id}/interview-response")
async def api_respond_to_interview(
    message_id: int,
    user_id: int = Query(...),
    body: InterviewResponseIn = Body(...),
    db: Session = Depends(get_db),
):
    """US-47: seeker accepts or declines. The employer is notified either
    way — that's the point of the story ("so employers know whether I can
    attend"), not just a silent status flip."""

    message = db.query(Message).filter(Message.id == message_id).first()
    if not message or message.message_type != "interview_invite" or not message.interview_invite:
        raise HTTPException(status_code=404, detail="Interview invitation not found.")

    _require_participant(message.conversation, "seeker", user_id)
    _require_unblocked(message.conversation)
    if message.sender_role != "employer":
        raise HTTPException(status_code=403, detail="Not the recipient of this invitation.")

    invite = message.interview_invite
    invite.status = body.response
    invite.responded_at = datetime.utcnow()

    seeker_name = _seeker_name(user_id, db)
    verb = "accepted" if body.response == "accepted" else "declined"
    _notify_recipient(
        db, "seeker", user_id, message.sender_id,
        f"{seeker_name} {verb} your interview invitation",
    )

    db.commit()
    db.refresh(message)

    return JSONResponse(content=_message_out(message))


@router.put("/api/messages/{message_id}/interview-reschedule")
async def api_reschedule_interview(
    message_id: int,
    employer_id: int = Query(...),
    body: InterviewInviteCreate = Body(...),
    db: Session = Depends(get_db),
):
    """US-XX: employer reschedules an interview they sent. Resets status
    back to 'pending' — a rescheduled time needs fresh confirmation, an
    old acceptance/decline no longer applies to the new slot."""

    message = db.query(Message).filter(Message.id == message_id).first()
    if not message or message.message_type != "interview_invite" or not message.interview_invite:
        raise HTTPException(status_code=404, detail="Interview invitation not found.")

    _require_participant(message.conversation, "employer", employer_id)
    _require_unblocked(message.conversation)
    if message.sender_role != "employer" or message.sender_id != employer_id:
        raise HTTPException(status_code=403, detail="Only the sender can reschedule this invitation.")

    invite = message.interview_invite
    if invite.status == "cancelled":
        raise HTTPException(status_code=400, detail="Can't reschedule a cancelled invitation.")

    invite.scheduled_at = body.scheduled_at
    invite.duration_minutes = body.duration_minutes
    invite.mode = body.mode
    invite.location_or_link = body.location_or_link or ""
    invite.notes = body.notes or ""
    invite.status = "pending"
    invite.responded_at = None

    message.conversation.last_message_at = datetime.utcnow()
    seeker_id = message.conversation.seeker_id
    _notify_recipient(
        db, "employer", employer_id, seeker_id,
        f"Interview rescheduled to {body.scheduled_at.strftime('%d %b, %I:%M %p')}",
    )

    db.commit()
    db.refresh(message)

    return JSONResponse(content=_message_out(message))


@router.post("/api/messages/{message_id}/interview-cancel")
async def api_cancel_interview(
    message_id: int,
    employer_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """US-XX: employer cancels an interview they sent. Kept visible in the
    thread as a cancelled card (not deleted) so there's a clear record,
    matching how declined invitations stay visible rather than vanishing."""

    message = db.query(Message).filter(Message.id == message_id).first()
    if not message or message.message_type != "interview_invite" or not message.interview_invite:
        raise HTTPException(status_code=404, detail="Interview invitation not found.")

    _require_participant(message.conversation, "employer", employer_id)
    _require_unblocked(message.conversation)
    if message.sender_role != "employer" or message.sender_id != employer_id:
        raise HTTPException(status_code=403, detail="Only the sender can cancel this invitation.")

    invite = message.interview_invite
    invite.status = "cancelled"
    invite.responded_at = datetime.utcnow()

    seeker_id = message.conversation.seeker_id
    _notify_recipient(
        db, "employer", employer_id, seeker_id,
        "Your interview invitation was cancelled",
    )

    db.commit()
    db.refresh(message)

    return JSONResponse(content=_message_out(message))


# ---------- Delete message ----------


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


# ---------- Delete / hide conversation ----------


@router.post("/api/conversations/{conversation_id}/block")
async def api_block_conversation_participant(
    conversation_id: int,
    role: str = Query(..., pattern="^(seeker|employer)$"),
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Block the other participant from this conversation. History remains
    readable, but neither participant can send new messages until the person
    who set the block removes it."""

    convo = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    _require_participant(convo, role, user_id)

    column = "blocked_by_seeker" if role == "seeker" else "blocked_by_employer"
    setattr(convo, column, 1)
    db.commit()
    return JSONResponse(content={"success": True, **_block_status(convo, role)})


@router.delete("/api/conversations/{conversation_id}/block")
async def api_unblock_conversation_participant(
    conversation_id: int,
    role: str = Query(..., pattern="^(seeker|employer)$"),
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Remove the requester's own block. A block set by the other party,
    if any, remains in force."""

    convo = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    _require_participant(convo, role, user_id)

    column = "blocked_by_seeker" if role == "seeker" else "blocked_by_employer"
    setattr(convo, column, 0)
    db.commit()
    return JSONResponse(content={"success": True, **_block_status(convo, role)})


@router.delete("/api/conversations/{conversation_id}")
async def api_delete_conversation(
    conversation_id: int,
    role: str = Query(..., pattern="^(seeker|employer)$"),
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Hides the whole thread from the requester's own inbox — like
    WhatsApp/Telegram's "Delete chat": it clears your view, it doesn't
    touch the other party's copy or actually erase the messages. If new
    activity happens afterwards, the conversation reappears for both
    parties (see _unhide_for_both), rather than staying permanently gone."""

    convo = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    _require_participant(convo, role, user_id)

    col = "hidden_for_seeker" if role == "seeker" else "hidden_for_employer"
    setattr(convo, col, 1)
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
    active conversation first, like a WhatsApp chat list. Threads the
    requester has "deleted" (hidden_for_<role>) are left out."""

    query = db.query(Conversation)
    if role == "seeker":
        query = query.filter(Conversation.seeker_id == user_id, Conversation.hidden_for_seeker == 0)
    else:
        query = query.filter(Conversation.employer_id == user_id, Conversation.hidden_for_employer == 0)
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
                **_block_status(convo, role),
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
    opening a thread is what clears its unread count, same as any chat app.
    Also used for polling (messages.html re-calls this every few seconds
    while a thread is open) to pick up new incoming messages."""

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
            **_block_status(convo, role),
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
    _require_unblocked(convo)
    db.commit()

    return JSONResponse(content={"conversation_id": convo.id})
