"""
Acceptance tests for the Messaging & Communication module.

US-40: seeker sends a message to an employer.
US-41: employer sends a message to a seeker.
US-42: seeker views received messages.
US-43: employer views received messages.

Style follows tests/test_employer.py: Given/When/Then docstrings, FastAPI's
TestClient against a throwaway SQLite DB (see conftest.py).
"""


def _send(client, sender_role, sender_id, recipient_id, body_text, job_id=None):
    payload = {
        "sender_role": sender_role,
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "body": body_text,
    }
    if job_id is not None:
        payload["job_id"] = job_id
    return client.post("/api/messages", json=payload)


# ---------------------------------------------------------------------------
# US-40: Seeker sends a message to an employer
# ---------------------------------------------------------------------------


def test_seeker_can_send_message_to_employer(client):
    """
    US-40: Seeker sends a message to an employer

    Given a job seeker wants to ask about a vacancy
    When I POST /api/messages as sender_role=seeker
    Then the message is created and attributed to the seeker
    """
    r = _send(client, "seeker", 1, 2, "Hi, is this role still open?")
    assert r.status_code == 200
    body = r.json()
    assert body["sender_role"] == "seeker"
    assert body["sender_id"] == 1
    assert body["body"] == "Hi, is this role still open?"


def test_seeker_message_can_optionally_reference_a_job(client):
    """
    Given a seeker is asking about a specific job posting
    When I POST /api/messages with job_id set
    Then the message carries that job tag, and job is optional otherwise
    """
    r = _send(client, "seeker", 1, 2, "Is remote work an option?", job_id=5)
    assert r.status_code == 200
    assert r.json()["job_id"] == 5

    r2 = _send(client, "seeker", 1, 2, "Just checking in generally.")
    assert r2.status_code == 200
    assert r2.json()["job_id"] is None


def test_empty_message_body_rejected(client):
    """
    Given a blank message body
    When I POST /api/messages
    Then I receive 422 Unprocessable Entity
    """
    r = _send(client, "seeker", 1, 2, "   ")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# US-41: Employer sends a message to a seeker
# ---------------------------------------------------------------------------


def test_employer_can_send_message_to_seeker(client):
    """
    US-41: Employer sends a message to a seeker

    Given an employer wants to share recruitment info
    When I POST /api/messages as sender_role=employer
    Then the message is created and attributed to the employer
    """
    r = _send(client, "employer", 2, 1, "We'd like to schedule an interview.")
    assert r.status_code == 200
    body = r.json()
    assert body["sender_role"] == "employer"
    assert body["sender_id"] == 2


def test_conversation_is_reused_across_messages(client):
    """
    Given a seeker and employer have already exchanged a message
    When either sends another message to the other
    Then both messages land in the same conversation (WhatsApp-style single
    thread per contact, not a new thread per message)
    """
    first = _send(client, "seeker", 1, 2, "Hello!").json()
    second = _send(client, "employer", 2, 1, "Hi there!").json()
    assert first["conversation_id"] == second["conversation_id"]


# ---------------------------------------------------------------------------
# US-42: Seeker views received messages
# ---------------------------------------------------------------------------


def test_seeker_sees_conversation_in_inbox(client):
    """
    US-42: Seeker views received messages

    Given an employer has messaged a seeker
    When the seeker GETs /api/conversations
    Then the conversation appears with a preview of the latest message
    """
    _send(client, "employer", 2, 1, "We reviewed your application.")
    r = client.get("/api/conversations?role=seeker&user_id=1")
    assert r.status_code == 200
    conversations = r.json()
    assert len(conversations) == 1
    assert conversations[0]["other_party_id"] == 2
    assert "reviewed" in conversations[0]["last_message_preview"]


def test_seeker_can_read_full_thread(client):
    """
    Given a seeker and employer have exchanged multiple messages
    When the seeker GETs the conversation's message list
    Then all messages appear in order
    """
    _send(client, "seeker", 1, 2, "Question 1")
    _send(client, "employer", 2, 1, "Answer 1")
    convo_id = client.get("/api/conversations?role=seeker&user_id=1").json()[0]["id"]

    r = client.get(f"/api/conversations/{convo_id}/messages?role=seeker&user_id=1")
    assert r.status_code == 200
    messages = r.json()["messages"]
    assert [m["body"] for m in messages] == ["Question 1", "Answer 1"]


def test_opening_thread_marks_incoming_messages_read(client):
    """
    Given an employer sent a seeker an unread message
    When the seeker opens the conversation
    Then that message becomes read, and the inbox unread count drops to 0
    """
    _send(client, "employer", 2, 1, "Are you still interested?")
    convo_id = client.get("/api/conversations?role=seeker&user_id=1").json()[0]["id"]
    before = client.get("/api/conversations?role=seeker&user_id=1").json()[0]
    assert before["unread_count"] == 1

    client.get(f"/api/conversations/{convo_id}/messages?role=seeker&user_id=1")

    after = client.get("/api/conversations?role=seeker&user_id=1").json()[0]
    assert after["unread_count"] == 0


def test_cannot_read_conversation_not_a_participant_in(client):
    """
    Given a conversation exists between seeker 1 and employer 2
    When seeker 3 (not a participant) tries to fetch it
    Then I receive 403 Forbidden
    """
    _send(client, "seeker", 1, 2, "Hi")
    convo_id = client.get("/api/conversations?role=seeker&user_id=1").json()[0]["id"]

    r = client.get(f"/api/conversations/{convo_id}/messages?role=seeker&user_id=3")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# US-43: Employer views received messages
# ---------------------------------------------------------------------------


def test_employer_sees_conversation_in_inbox(client):
    """
    US-43: Employer views received messages

    Given a seeker has messaged an employer
    When the employer GETs /api/conversations
    Then the conversation appears with the seeker as the other party
    """
    _send(client, "seeker", 1, 2, "Can you tell me more about the role?")
    r = client.get("/api/conversations?role=employer&user_id=2")
    assert r.status_code == 200
    conversations = r.json()
    assert len(conversations) == 1
    assert conversations[0]["other_party_id"] == 1


def test_employer_inbox_scoped_to_own_conversations(client):
    """
    Given employer 2 and employer 3 each have separate conversations with seeker 1
    When employer 3 fetches their inbox
    Then only their own conversation is returned
    """
    _send(client, "seeker", 1, 2, "Message to employer 2")
    _send(client, "seeker", 1, 3, "Message to employer 3")

    r = client.get("/api/conversations?role=employer&user_id=3")
    conversations = r.json()
    assert len(conversations) == 1
    assert conversations[0]["other_party_id"] == 1
    assert "employer 3" in conversations[0]["last_message_preview"]


# ---------------------------------------------------------------------------
# Notifications on send (recipient only, never the sender)
# ---------------------------------------------------------------------------


def test_sending_message_notifies_recipient_not_sender(client):
    """
    Given a seeker sends a message to an employer
    When I check each party's notifications
    Then the employer (recipient) has a new-message notification
    And the seeker (sender) does not
    """
    _send(client, "seeker", 1, 2, "Quick question about the role.")

    employer_notifs = client.get("/api/notifications?role=employer&user_id=2").json()
    assert len(employer_notifs) == 1
    assert "message" in employer_notifs[0]["title"].lower()

    seeker_notifs = client.get("/api/notifications?role=seeker&user_id=1").json()
    assert seeker_notifs == []


def test_employer_message_notifies_seeker(client):
    """
    Given an employer sends a message to a seeker
    When the seeker checks their notifications
    Then a new-message notification is present
    """
    _send(client, "employer", 2, 1, "You're shortlisted!")
    seeker_notifs = client.get("/api/notifications?role=seeker&user_id=1").json()
    assert len(seeker_notifs) == 1


def test_existing_seeker_notifications_endpoint_still_works(client):
    """
    Given the original call shape used by notifications.html (?seeker_id=1)
    When I GET /api/notifications with just seeker_id (no role/user_id)
    Then it still returns that seeker's notifications (backwards compatible)
    """
    _send(client, "employer", 2, 1, "Hello")
    r = client.get("/api/notifications?seeker_id=1")
    assert r.status_code == 200
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# Encryption at rest
# ---------------------------------------------------------------------------


def test_message_body_stored_encrypted_at_rest(client, db_session):
    """
    Given a message is sent
    When I read the raw DB row directly (bypassing the API)
    Then the stored body is not the plaintext (it's encrypted), while the
    API still returns the readable plaintext to the client
    """
    from job_portal.models import Message

    r = _send(client, "seeker", 1, 2, "This is a secret question.")
    assert r.json()["body"] == "This is a secret question."

    row = db_session.query(Message).filter(Message.id == r.json()["id"]).first()
    assert row.body != "This is a secret question."
    assert "secret" not in row.body


# ---------------------------------------------------------------------------
# Edit message
# ---------------------------------------------------------------------------


def test_sender_can_edit_message_within_window(client):
    """
    Given a seeker just sent a message
    When they PUT a new body within the edit window
    Then the message updates and is flagged as edited
    """
    sent = _send(client, "seeker", 1, 2, "Orginal typo").json()
    r = client.put(
        f"/api/messages/{sent['id']}?role=seeker&user_id=1",
        json={"body": "Original, fixed"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["body"] == "Original, fixed"
    assert body["is_edited"] is True


def test_only_sender_can_edit_message(client):
    """
    Given an employer sent a message
    When the seeker (recipient) tries to edit it
    Then I receive 403 Forbidden
    """
    sent = _send(client, "employer", 2, 1, "Original").json()
    r = client.put(
        f"/api/messages/{sent['id']}?role=seeker&user_id=1",
        json={"body": "Hacked"},
    )
    assert r.status_code == 403


def test_cannot_edit_after_edit_window_expires(client, db_session):
    """
    Given a message was sent more than 15 minutes ago
    When the sender tries to edit it
    Then I receive 400 Bad Request
    """
    from datetime import datetime, timedelta

    from job_portal.models import Message

    sent = _send(client, "seeker", 1, 2, "Old message").json()
    row = db_session.query(Message).filter(Message.id == sent["id"]).first()
    row.created_at = datetime.utcnow() - timedelta(minutes=20)
    db_session.commit()

    r = client.put(
        f"/api/messages/{sent['id']}?role=seeker&user_id=1",
        json={"body": "Too late"},
    )
    assert r.status_code == 400


def test_edit_rejects_blank_body(client):
    """
    Given a sent message
    When editing it to a blank body
    Then I receive 422 Unprocessable Entity
    """
    sent = _send(client, "seeker", 1, 2, "Original").json()
    r = client.put(
        f"/api/messages/{sent['id']}?role=seeker&user_id=1",
        json={"body": "   "},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Delete message
# ---------------------------------------------------------------------------


def test_delete_for_me_hides_only_for_requester(client):
    """
    Given a message exists in a conversation
    When the recipient deletes it "for me"
    Then it disappears from their view but the sender still sees it
    """
    sent = _send(client, "seeker", 1, 2, "Visible to sender only after this").json()
    convo_id = sent["conversation_id"]

    r = client.delete(f"/api/messages/{sent['id']}?role=employer&user_id=2&scope=me")
    assert r.status_code == 200

    employer_view = client.get(f"/api/conversations/{convo_id}/messages?role=employer&user_id=2")
    assert employer_view.json()["messages"] == []

    seeker_view = client.get(f"/api/conversations/{convo_id}/messages?role=seeker&user_id=1")
    assert len(seeker_view.json()["messages"]) == 1


def test_delete_for_everyone_shows_placeholder_to_both(client):
    """
    Given a seeker sent a message
    When they delete it "for everyone"
    Then both parties see a "deleted" placeholder instead of the content
    """
    sent = _send(client, "seeker", 1, 2, "Oops wrong chat").json()
    convo_id = sent["conversation_id"]

    r = client.delete(f"/api/messages/{sent['id']}?role=seeker&user_id=1&scope=everyone")
    assert r.status_code == 200

    for role, uid in [("seeker", 1), ("employer", 2)]:
        thread = client.get(f"/api/conversations/{convo_id}/messages?role={role}&user_id={uid}")
        msg = thread.json()["messages"][0]
        assert msg["is_deleted"] is True
        assert msg["body"] == "This message was deleted"


def test_only_sender_can_delete_for_everyone(client):
    """
    Given an employer sent a message
    When the seeker (recipient) tries to delete it "for everyone"
    Then I receive 403 Forbidden
    """
    sent = _send(client, "employer", 2, 1, "Careful message").json()
    r = client.delete(f"/api/messages/{sent['id']}?role=seeker&user_id=1&scope=everyone")
    assert r.status_code == 403


def test_recipient_can_delete_received_message_for_me(client):
    """
    Given a recipient received a message they don't want to see anymore
    When they delete it with scope=me (not the sender)
    Then it's allowed (deleting "for me" doesn't require being the sender)
    """
    sent = _send(client, "employer", 2, 1, "Some message").json()
    r = client.delete(f"/api/messages/{sent['id']}?role=seeker&user_id=1&scope=me")
    assert r.status_code == 200


def test_cannot_delete_message_not_a_participant_in(client):
    """
    Given a conversation between seeker 1 and employer 2
    When seeker 3 (not a participant) tries to delete a message in it
    Then I receive 403 Forbidden
    """
    sent = _send(client, "seeker", 1, 2, "Private").json()
    r = client.delete(f"/api/messages/{sent['id']}?role=seeker&user_id=3&scope=me")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "3df40000000c4944415408d763f8ffff3f0005fe02fea1399e3f0000000049454e44ae426082"
)


def test_send_image_attachment(client):
    """
    Given a seeker attaches a small PNG image
    When they POST /api/messages/attachment
    Then the message is created with attachment metadata and type "image"
    """
    r = client.post(
        "/api/messages/attachment",
        data={"sender_role": "seeker", "sender_id": 1, "recipient_id": 2, "body": "See attached"},
        files={"file": ("screenshot.png", _PNG_1PX, "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["attachment_type"] == "image"
    assert body["attachment_url"] == f"/api/messages/{body['id']}/attachment"
    assert body["body"] == "See attached"


def test_attachment_without_caption_is_valid(client):
    """
    Given a seeker sends just an image with no text
    When they POST /api/messages/attachment with an empty body
    Then the message is still created successfully
    """
    r = client.post(
        "/api/messages/attachment",
        data={"sender_role": "seeker", "sender_id": 1, "recipient_id": 2},
        files={"file": ("photo.png", _PNG_1PX, "image/png")},
    )
    assert r.status_code == 200
    assert r.json()["body"] == ""


def test_attachment_rejects_disallowed_file_type(client):
    """
    Given a file that isn't a recognized image/document format
    When it's uploaded as a message attachment
    Then I receive 422 Unprocessable Entity, regardless of claimed content-type
    """
    r = client.post(
        "/api/messages/attachment",
        data={"sender_role": "seeker", "sender_id": 1, "recipient_id": 2},
        files={"file": ("script.exe", b"not a real file format", "application/octet-stream")},
    )
    assert r.status_code == 422


def test_conversation_preview_shows_attachment_indicator(client):
    """
    Given the latest message in a conversation is an attachment with no caption
    When viewing the inbox
    Then the preview indicates an attachment was sent
    """
    _send_attachment = client.post(
        "/api/messages/attachment",
        data={"sender_role": "seeker", "sender_id": 1, "recipient_id": 2},
        files={"file": ("resume.png", _PNG_1PX, "image/png")},
    )
    assert _send_attachment.status_code == 200

    r = client.get("/api/conversations?role=employer&user_id=2")
    assert "📎" in r.json()[0]["last_message_preview"]


def test_attachment_stored_encrypted_on_disk(client):
    """
    Given an image attachment is sent
    When I read the raw file bytes straight off disk (bypassing the API)
    Then the bytes are not a valid PNG (they're encrypted) — the API
    endpoint is the only way to get the real, decrypted file back
    """
    from job_portal.models import Message

    sent = client.post(
        "/api/messages/attachment",
        data={"sender_role": "seeker", "sender_id": 1, "recipient_id": 2},
        files={"file": ("photo.png", _PNG_1PX, "image/png")},
    ).json()

    from job_portal.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(Message).filter(Message.id == sent["id"]).first()
        with open(row.attachment_url, "rb") as fh:
            raw_bytes = fh.read()
        assert raw_bytes != _PNG_1PX
        assert not raw_bytes.startswith(b"\x89PNG")
    finally:
        db.close()


def test_authorized_participant_can_fetch_decrypted_attachment(client):
    """
    Given an attachment was sent to an employer
    When the employer fetches it via the attachment endpoint
    Then they get back the original, decrypted image bytes
    """
    sent = client.post(
        "/api/messages/attachment",
        data={"sender_role": "seeker", "sender_id": 1, "recipient_id": 2},
        files={"file": ("photo.png", _PNG_1PX, "image/png")},
    ).json()

    r = client.get(f"/api/messages/{sent['id']}/attachment?role=employer&user_id=2")
    assert r.status_code == 200
    assert r.content == _PNG_1PX
    assert r.headers["content-type"] == "image/png"


def test_non_participant_cannot_fetch_attachment(client):
    """
    Given an attachment exists in a seeker-1/employer-2 conversation
    When employer 3 (not a participant) tries to fetch it
    Then I receive 403 Forbidden
    """
    sent = client.post(
        "/api/messages/attachment",
        data={"sender_role": "seeker", "sender_id": 1, "recipient_id": 2},
        files={"file": ("photo.png", _PNG_1PX, "image/png")},
    ).json()

    r = client.get(f"/api/messages/{sent['id']}/attachment?role=employer&user_id=3")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Delete conversation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Block user
# ---------------------------------------------------------------------------


def test_seeker_can_block_and_unblock_an_employer(client):
    """A seeker can stop a conversation and later resume it themselves."""
    sent = _send(client, "seeker", 1, 2, "Hello").json()
    convo_id = sent["conversation_id"]

    blocked = client.post(f"/api/conversations/{convo_id}/block?role=seeker&user_id=1")
    assert blocked.status_code == 200
    assert blocked.json()["is_blocked"] is True
    assert blocked.json()["blocked_by_me"] is True

    seeker_thread = client.get(f"/api/conversations/{convo_id}/messages?role=seeker&user_id=1")
    employer_thread = client.get(f"/api/conversations/{convo_id}/messages?role=employer&user_id=2")
    assert seeker_thread.json()["blocked_by_me"] is True
    assert employer_thread.json()["is_blocked"] is True
    assert employer_thread.json()["blocked_by_me"] is False

    rejected = _send(client, "employer", 2, 1, "Can you reply?")
    assert rejected.status_code == 403

    unblocked = client.delete(f"/api/conversations/{convo_id}/block?role=seeker&user_id=1")
    assert unblocked.status_code == 200
    assert unblocked.json()["is_blocked"] is False
    assert _send(client, "employer", 2, 1, "Thanks").status_code == 200


def test_employer_can_block_a_seeker_and_block_prevents_attachments(client):
    """The same protection applies from the employer view and to attachments."""
    sent = _send(client, "seeker", 1, 2, "Hello").json()
    convo_id = sent["conversation_id"]
    assert client.post(f"/api/conversations/{convo_id}/block?role=employer&user_id=2").status_code == 200

    attachment = client.post(
        "/api/messages/attachment",
        data={"sender_role": "seeker", "sender_id": "1", "recipient_id": "2", "body": ""},
        files={"file": ("note.png", _PNG_1PX, "image/png")},
    )
    assert attachment.status_code == 403


def test_non_participant_cannot_block_conversation(client):
    sent = _send(client, "seeker", 1, 2, "Hello").json()
    r = client.post(f"/api/conversations/{sent['conversation_id']}/block?role=seeker&user_id=3")
    assert r.status_code == 403


def test_delete_conversation_hides_it_only_for_requester(client):
    """
    Given a conversation between a seeker and employer
    When the seeker deletes the conversation
    Then it disappears from the seeker's inbox but the employer still sees it
    """
    sent = _send(client, "seeker", 1, 2, "Hello").json()
    convo_id = sent["conversation_id"]

    r = client.delete(f"/api/conversations/{convo_id}?role=seeker&user_id=1")
    assert r.status_code == 200

    seeker_inbox = client.get("/api/conversations?role=seeker&user_id=1").json()
    assert seeker_inbox == []

    employer_inbox = client.get("/api/conversations?role=employer&user_id=2").json()
    assert len(employer_inbox) == 1


def test_deleted_conversation_reappears_on_new_message(client):
    """
    Given a seeker deleted a conversation from their inbox
    When a new message arrives in that conversation
    Then it reappears in the seeker's inbox too (matches WhatsApp/Telegram
    "delete chat" behavior — it's not a permanent block)
    """
    sent = _send(client, "seeker", 1, 2, "Hello").json()
    convo_id = sent["conversation_id"]
    client.delete(f"/api/conversations/{convo_id}?role=seeker&user_id=1")
    assert client.get("/api/conversations?role=seeker&user_id=1").json() == []

    _send(client, "employer", 2, 1, "Following up")

    seeker_inbox = client.get("/api/conversations?role=seeker&user_id=1").json()
    assert len(seeker_inbox) == 1


def test_cannot_delete_conversation_not_a_participant_in(client):
    """
    Given a conversation between seeker 1 and employer 2
    When seeker 3 tries to delete it
    Then I receive 403 Forbidden
    """
    sent = _send(client, "seeker", 1, 2, "Hello").json()
    convo_id = sent["conversation_id"]
    r = client.delete(f"/api/conversations/{convo_id}?role=seeker&user_id=3")
    assert r.status_code == 403
