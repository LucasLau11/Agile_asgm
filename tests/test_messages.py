"""
Acceptance tests for the Messaging & Communication module.

US-40: seeker sends a message to an employer.
US-41: employer sends a message to a seeker.
US-42: seeker views received messages.
US-43: employer views received messages.

Style follows tests/test_employer.py: Given/When/Then docstrings, FastAPI's
TestClient against a throwaway SQLite DB (see conftest.py).

Phase 2e retrofit note: POST /api/messages, POST /api/messages/attachment,
GET /api/messages/{id}/attachment, PUT /api/messages/{id},
DELETE /api/messages/{id}, GET /api/conversations,
GET /api/conversations/{id}/messages, POST /api/conversations/find-or-create,
POST//DELETE /api/conversations/{id}/block, and DELETE /api/conversations/{id}
now derive the actor identity from the session
(Depends(require_participant_role())) rather than a client-supplied
sender_role/sender_id or role/user_id. Every test below that touches one of
those endpoints logs in first via _login_new_seeker/_login_new_employer/
_login, and no longer passes an id representing "who's acting" to them.
Where a test needs a specific counterparty to exist (rather than just "some
other party who isn't a participant"), a real second account is registered
and its real id is used in place of what used to be an arbitrary hardcoded
number like `user_id=2` or `user_id=999999`.

The four interview-invitation endpoints (send/respond/reschedule/cancel)
are also retrofitted (Task 3): send/reschedule/cancel derive employer_id
from Depends(require_role("employer")), and response derives user_id from
Depends(require_role("seeker")) — none of them take a client-supplied
employer_id/user_id query param anymore. This file has no direct tests
against those four endpoints; their auth/identity behavior is covered in
tests/test_messages_auth.py.
"""


def _send(client, recipient_id, body_text, job_id=None):
    payload = {"recipient_id": recipient_id, "body": body_text}
    if job_id is not None:
        payload["job_id"] = job_id
    return client.post("/api/messages", json=payload)


def _login_new_seeker(client, tag, full_name="Test Seeker"):
    # Real-recipient validation requires the formerly hard-coded IDs 1/2
    # used by legacy cases below to correspond to actual employer rows.
    for index in (1, 2):
        response = client.post("/api/auth/register/employer", json={
            "company_name": f"Contact Employer {tag}-{index}",
            "email": f"contact-employer-{tag}-{index}@example.com",
            "password": "correcthorse",
        })
        assert response.status_code == 201, response.text
        client.post("/api/auth/logout")
    client.post("/api/auth/register/seeker", json={
        "full_name": full_name,
        "email": f"seeker-{tag}@example.com",
        "password": "correcthorse",
    })


def _login_new_employer(client, tag, company_name="Test Co"):
    # Likewise ensure the legacy recipient IDs refer to real seekers.
    for index, word in ((1, "One"), (2, "Two")):
        response = client.post("/api/auth/register/seeker", json={
            "full_name": f"Contact Seeker {word}",
            "email": f"contact-seeker-{tag}-{index}@example.com",
            "password": "correcthorse",
        })
        assert response.status_code == 201, response.text
        client.post("/api/auth/logout")
    response = client.post("/api/auth/register/employer", json={
        "company_name": company_name,
        "email": f"employer-{tag}@example.com",
        "password": "correcthorse",
    })
    assert response.status_code == 201, response.text


def _login(client, email, password="correcthorse"):
    client.post("/api/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------------------
# US-40: Seeker sends a message to an employer
# ---------------------------------------------------------------------------


def test_seeker_can_send_message_to_employer(client):
    """
    US-40: Seeker sends a message to an employer

    Given a job seeker wants to ask about a vacancy
    When I POST /api/messages while logged in as a seeker
    Then the message is created and attributed to the seeker
    """
    _login_new_seeker(client, "send1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]

    r = _send(client, 2, "Hi, is this role still open?")
    assert r.status_code == 200
    body = r.json()
    assert body["sender_role"] == "seeker"
    assert body["sender_id"] == seeker_id
    assert body["body"] == "Hi, is this role still open?"


def test_seeker_message_can_optionally_reference_a_job(client):
    """
    Given a seeker is asking about a specific job posting
    When I POST /api/messages with job_id set
    Then the message carries that job tag, and job is optional otherwise
    """
    _login_new_seeker(client, "job1")

    r = _send(client, 2, "Is remote work an option?", job_id=5)
    assert r.status_code == 200
    assert r.json()["job_id"] == 5

    r2 = _send(client, 2, "Just checking in generally.")
    assert r2.status_code == 200
    assert r2.json()["job_id"] is None


def test_empty_message_body_rejected(client):
    """
    Given a blank message body
    When I POST /api/messages
    Then I receive 422 Unprocessable Entity
    """
    _login_new_seeker(client, "empty1")
    r = _send(client, 2, "   ")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# US-41: Employer sends a message to a seeker
# ---------------------------------------------------------------------------


def test_employer_can_send_message_to_seeker(client):
    """
    US-41: Employer sends a message to a seeker

    Given an employer wants to share recruitment info
    When I POST /api/messages while logged in as an employer
    Then the message is created and attributed to the employer
    """
    _login_new_employer(client, "employersend1")
    employer_id = client.get("/api/auth/me").json()["id"]

    r = _send(client, 1, "We'd like to schedule an interview.")
    assert r.status_code == 200
    body = r.json()
    assert body["sender_role"] == "employer"
    assert body["sender_id"] == employer_id


def test_conversation_is_reused_across_messages(client):
    """
    Given a seeker and employer have already exchanged a message
    When either sends another message to the other
    Then both messages land in the same conversation (WhatsApp-style single
    thread per contact, not a new thread per message)
    """
    _login_new_seeker(client, "reuse1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "reuse1")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login(client, "seeker-reuse1@example.com")
    first = _send(client, employer_id, "Hello!").json()
    client.post("/api/auth/logout")

    _login(client, "employer-reuse1@example.com")
    second = _send(client, seeker_id, "Hi there!").json()

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
    _login_new_seeker(client, "inbox1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "inbox1")
    employer_id = client.get("/api/auth/me").json()["id"]
    _send(client, seeker_id, "We reviewed your application.")
    client.post("/api/auth/logout")

    _login(client, "seeker-inbox1@example.com")
    r = client.get("/api/conversations")
    assert r.status_code == 200
    conversations = r.json()
    assert len(conversations) == 1
    assert conversations[0]["other_party_id"] == employer_id
    assert "reviewed" in conversations[0]["last_message_preview"]


def test_seeker_can_read_full_thread(client):
    """
    Given a seeker and employer have exchanged multiple messages
    When the seeker GETs the conversation's message list
    Then all messages appear in order
    """
    _login_new_seeker(client, "thread1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "thread1")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login(client, "seeker-thread1@example.com")
    _send(client, employer_id, "Question 1")
    client.post("/api/auth/logout")

    _login(client, "employer-thread1@example.com")
    _send(client, seeker_id, "Answer 1")
    client.post("/api/auth/logout")

    _login(client, "seeker-thread1@example.com")
    convo_id = client.get("/api/conversations").json()[0]["id"]

    r = client.get(f"/api/conversations/{convo_id}/messages")
    assert r.status_code == 200
    messages = r.json()["messages"]
    assert [m["body"] for m in messages] == ["Question 1", "Answer 1"]


def test_opening_thread_marks_incoming_messages_read(client):
    """
    Given an employer sent a seeker an unread message
    When the seeker opens the conversation
    Then that message becomes read, and the inbox unread count drops to 0
    """
    _login_new_seeker(client, "unread1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "unread1")
    _send(client, seeker_id, "Are you still interested?")
    client.post("/api/auth/logout")

    _login(client, "seeker-unread1@example.com")
    convo_id = client.get("/api/conversations").json()[0]["id"]
    before = client.get("/api/conversations").json()[0]
    assert before["unread_count"] == 1

    client.get(f"/api/conversations/{convo_id}/messages")

    after = client.get("/api/conversations").json()[0]
    assert after["unread_count"] == 0


def test_cannot_read_conversation_not_a_participant_in(client):
    """
    Given a conversation exists between a seeker and an employer
    When an unrelated seeker (not a participant) tries to fetch it
    Then I receive 403 Forbidden
    """
    _login_new_seeker(client, "readvictim1")
    _send(client, 2, "Hi")
    convo_id = client.get("/api/conversations").json()[0]["id"]
    client.post("/api/auth/logout")

    _login_new_seeker(client, "readoutsider1")

    r = client.get(f"/api/conversations/{convo_id}/messages")
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
    _login_new_seeker(client, "employerinbox1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "employerinbox1")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login(client, "seeker-employerinbox1@example.com")
    _send(client, employer_id, "Can you tell me more about the role?")
    client.post("/api/auth/logout")

    _login(client, "employer-employerinbox1@example.com")
    r = client.get("/api/conversations")
    assert r.status_code == 200
    conversations = r.json()
    assert len(conversations) == 1
    assert conversations[0]["other_party_id"] == seeker_id


def test_employer_inbox_scoped_to_own_conversations(client):
    """
    Given employer A and employer B each have separate conversations with the
    same seeker
    When employer B fetches their inbox
    Then only their own conversation is returned
    """
    _login_new_seeker(client, "employerscoped1")
    client.post("/api/auth/logout")

    _login_new_employer(client, "employerscopedA")
    employer_a_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "employerscopedB")
    employer_b_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login(client, "seeker-employerscoped1@example.com")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    _send(client, employer_a_id, "Message to employer A")
    _send(client, employer_b_id, "Message to employer B")
    client.post("/api/auth/logout")

    _login(client, "employer-employerscopedB@example.com")
    r = client.get("/api/conversations")
    conversations = r.json()
    assert len(conversations) == 1
    assert conversations[0]["other_party_id"] == seeker_id
    assert "employer B" in conversations[0]["last_message_preview"]


# ---------------------------------------------------------------------------
# Notifications on send (recipient only, never the sender)
# ---------------------------------------------------------------------------


def test_sending_message_notifies_recipient_not_sender(client):
    """
    Given a seeker sends a message to an employer
    When I check each party's notifications
    Then the employer (recipient) has a new-message notification
    And the seeker (sender) does not

    /api/notifications is role-agnostic and session-derived as of the
    phase-2d notifications retrofit — there is no more client-suppliable
    role/user_id query shape, so each party's notifications are checked
    by actually logging in as that party rather than passing their id.
    """
    _login_new_seeker(client, "notifmsgseeker")
    client.post("/api/auth/logout")

    _login_new_employer(client, "notifmsgemployer")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login(client, "seeker-notifmsgseeker@example.com")
    _send(client, employer_id, "Quick question about the role.")
    client.post("/api/auth/logout")

    _login(client, "employer-notifmsgemployer@example.com")
    employer_notifs = client.get("/api/notifications").json()
    assert len(employer_notifs) == 1
    assert "message" in employer_notifs[0]["title"].lower()
    client.post("/api/auth/logout")

    _login(client, "seeker-notifmsgseeker@example.com")
    seeker_notifs = client.get("/api/notifications").json()
    assert seeker_notifs == []


def test_employer_message_notifies_seeker(client):
    """
    Given an employer sends a message to a seeker
    When the seeker checks their notifications
    Then a new-message notification is present
    """
    _login_new_employer(client, "notifmsgemployer2")
    client.post("/api/auth/logout")

    _login_new_seeker(client, "notifmsgseeker2")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login(client, "employer-notifmsgemployer2@example.com")
    _send(client, seeker_id, "You're shortlisted!")
    client.post("/api/auth/logout")

    _login(client, "seeker-notifmsgseeker2@example.com")
    seeker_notifs = client.get("/api/notifications").json()
    assert len(seeker_notifs) == 1


# Note: there used to be a test_existing_seeker_notifications_endpoint_still_works
# here, asserting that GET /api/notifications?seeker_id=1 worked unauthenticated
# as a "backwards compatible" call shape. The phase-2d notifications retrofit
# deliberately removes that client-suppliable/unauthenticated path — identity
# now comes only from the session (see api_get_notifications in
# routes/applications.py) — so that behavior no longer exists by design, and
# the test asserting it is obsolete. Session-derived coverage for
# /api/notifications (including the 401-when-logged-out case) lives in
# tests/test_applications.py.


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

    _login_new_seeker(client, "encrypt1")
    r = _send(client, 2, "This is a secret question.")
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
    _login_new_seeker(client, "editwindow1")
    sent = _send(client, 2, "Orginal typo").json()
    r = client.put(f"/api/messages/{sent['id']}", json={"body": "Original, fixed"})
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
    _login_new_employer(client, "editonly1")
    sent = _send(client, 1, "Original").json()
    client.post("/api/auth/logout")

    _login_new_seeker(client, "editonly1")
    r = client.put(f"/api/messages/{sent['id']}", json={"body": "Hacked"})
    assert r.status_code == 403


def test_cannot_edit_after_edit_window_expires(client, db_session):
    """
    Given a message was sent more than 15 minutes ago
    When the sender tries to edit it
    Then I receive 400 Bad Request
    """
    from datetime import datetime, timedelta

    from job_portal.models import Message

    _login_new_seeker(client, "editexpire1")
    sent = _send(client, 2, "Old message").json()
    row = db_session.query(Message).filter(Message.id == sent["id"]).first()
    row.created_at = datetime.utcnow() - timedelta(minutes=20)
    db_session.commit()

    r = client.put(f"/api/messages/{sent['id']}", json={"body": "Too late"})
    assert r.status_code == 400


def test_edit_rejects_blank_body(client):
    """
    Given a sent message
    When editing it to a blank body
    Then I receive 422 Unprocessable Entity
    """
    _login_new_seeker(client, "editblank1")
    sent = _send(client, 2, "Original").json()
    r = client.put(f"/api/messages/{sent['id']}", json={"body": "   "})
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
    _login_new_employer(client, "delme1")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login_new_seeker(client, "delme1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    sent = _send(client, employer_id, "Visible to sender only after this").json()
    convo_id = sent["conversation_id"]
    client.post("/api/auth/logout")

    _login(client, "employer-delme1@example.com")
    r = client.delete(f"/api/messages/{sent['id']}?scope=me")
    assert r.status_code == 200

    employer_view = client.get(f"/api/conversations/{convo_id}/messages")
    assert employer_view.json()["messages"] == []
    client.post("/api/auth/logout")

    _login(client, "seeker-delme1@example.com")
    seeker_view = client.get(f"/api/conversations/{convo_id}/messages")
    assert len(seeker_view.json()["messages"]) == 1


def test_delete_for_everyone_shows_placeholder_to_both(client):
    """
    Given a seeker sent a message
    When they delete it "for everyone"
    Then both parties see a "deleted" placeholder instead of the content
    """
    _login_new_employer(client, "deleverybody1")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login_new_seeker(client, "deleverybody1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    sent = _send(client, employer_id, "Oops wrong chat").json()
    convo_id = sent["conversation_id"]

    r = client.delete(f"/api/messages/{sent['id']}?scope=everyone")
    assert r.status_code == 200
    client.post("/api/auth/logout")

    for email in [
        "seeker-deleverybody1@example.com",
        "employer-deleverybody1@example.com",
    ]:
        _login(client, email)
        thread = client.get(f"/api/conversations/{convo_id}/messages")
        msg = thread.json()["messages"][0]
        assert msg["is_deleted"] is True
        assert msg["body"] == "This message was deleted"
        client.post("/api/auth/logout")


def test_only_sender_can_delete_for_everyone(client):
    """
    Given an employer sent a message
    When the seeker (recipient) tries to delete it "for everyone"
    Then I receive 403 Forbidden
    """
    _login_new_seeker(client, "delonlysender1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "delonlysender1")
    sent = _send(client, seeker_id, "Careful message").json()
    client.post("/api/auth/logout")

    _login(client, "seeker-delonlysender1@example.com")
    r = client.delete(f"/api/messages/{sent['id']}?scope=everyone")
    assert r.status_code == 403


def test_recipient_can_delete_received_message_for_me(client):
    """
    Given a recipient received a message they don't want to see anymore
    When they delete it with scope=me (not the sender)
    Then it's allowed (deleting "for me" doesn't require being the sender)
    """
    _login_new_seeker(client, "delrecipient1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "delrecipient1")
    sent = _send(client, seeker_id, "Some message").json()
    client.post("/api/auth/logout")

    _login(client, "seeker-delrecipient1@example.com")
    r = client.delete(f"/api/messages/{sent['id']}?scope=me")
    assert r.status_code == 200


def test_cannot_delete_message_not_a_participant_in(client):
    """
    Given a conversation between a seeker and an employer
    When an unrelated seeker (not a participant) tries to delete a message in it
    Then I receive 403 Forbidden
    """
    _login_new_seeker(client, "delnonpartvictim1")
    sent = _send(client, 2, "Private").json()
    client.post("/api/auth/logout")

    _login_new_seeker(client, "delnonpartoutsider1")
    r = client.delete(f"/api/messages/{sent['id']}?scope=me")
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
    _login_new_seeker(client, "attach1")
    r = client.post(
        "/api/messages/attachment",
        data={"recipient_id": 2, "body": "See attached"},
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
    _login_new_seeker(client, "attachnocaption1")
    r = client.post(
        "/api/messages/attachment",
        data={"recipient_id": 2},
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
    _login_new_seeker(client, "attachbadtype1")
    r = client.post(
        "/api/messages/attachment",
        data={"recipient_id": 2},
        files={"file": ("script.exe", b"not a real file format", "application/octet-stream")},
    )
    assert r.status_code == 422


def test_conversation_preview_shows_attachment_indicator(client):
    """
    Given the latest message in a conversation is an attachment with no caption
    When viewing the inbox
    Then the preview indicates an attachment was sent
    """
    _login_new_employer(client, "attachpreview1")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login_new_seeker(client, "attachpreview1")
    _send_attachment = client.post(
        "/api/messages/attachment",
        data={"recipient_id": employer_id},
        files={"file": ("resume.png", _PNG_1PX, "image/png")},
    )
    assert _send_attachment.status_code == 200
    client.post("/api/auth/logout")

    _login(client, "employer-attachpreview1@example.com")
    r = client.get("/api/conversations")
    assert "📎" in r.json()[0]["last_message_preview"]


def test_attachment_stored_encrypted_on_disk(client):
    """
    Given an image attachment is sent
    When I read the raw file bytes straight off disk (bypassing the API)
    Then the bytes are not a valid PNG (they're encrypted) — the API
    endpoint is the only way to get the real, decrypted file back
    """
    from job_portal.models import Message

    _login_new_seeker(client, "attachdisk1")
    sent = client.post(
        "/api/messages/attachment",
        data={"recipient_id": 2},
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
    _login_new_employer(client, "attachfetch1")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login_new_seeker(client, "attachfetch1")
    sent = client.post(
        "/api/messages/attachment",
        data={"recipient_id": employer_id},
        files={"file": ("photo.png", _PNG_1PX, "image/png")},
    ).json()
    client.post("/api/auth/logout")

    _login(client, "employer-attachfetch1@example.com")
    r = client.get(f"/api/messages/{sent['id']}/attachment")
    assert r.status_code == 200
    assert r.content == _PNG_1PX
    assert r.headers["content-type"] == "image/png"


def test_non_participant_cannot_fetch_attachment(client):
    """
    Given an attachment exists in a seeker/employer conversation
    When an unrelated employer (not a participant) tries to fetch it
    Then I receive 403 Forbidden
    """
    _login_new_seeker(client, "attachnonpart1")
    sent = client.post(
        "/api/messages/attachment",
        data={"recipient_id": 2},
        files={"file": ("photo.png", _PNG_1PX, "image/png")},
    ).json()
    client.post("/api/auth/logout")

    _login_new_employer(client, "attachnonpart1")
    r = client.get(f"/api/messages/{sent['id']}/attachment")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Delete conversation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Block user
# ---------------------------------------------------------------------------


def test_seeker_can_block_and_unblock_an_employer(client):
    """A seeker can stop a conversation and later resume it themselves."""
    _login_new_employer(client, "block1")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login_new_seeker(client, "block1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    sent = _send(client, employer_id, "Hello").json()
    convo_id = sent["conversation_id"]

    blocked = client.post(f"/api/conversations/{convo_id}/block")
    assert blocked.status_code == 200
    assert blocked.json()["is_blocked"] is True
    assert blocked.json()["blocked_by_me"] is True

    seeker_thread = client.get(f"/api/conversations/{convo_id}/messages")
    assert seeker_thread.json()["blocked_by_me"] is True
    client.post("/api/auth/logout")

    _login(client, "employer-block1@example.com")
    employer_thread = client.get(f"/api/conversations/{convo_id}/messages")
    assert employer_thread.json()["is_blocked"] is True
    assert employer_thread.json()["blocked_by_me"] is False

    rejected = _send(client, seeker_id, "Can you reply?")
    assert rejected.status_code == 403
    client.post("/api/auth/logout")

    _login(client, "seeker-block1@example.com")
    unblocked = client.delete(f"/api/conversations/{convo_id}/block")
    assert unblocked.status_code == 200
    assert unblocked.json()["is_blocked"] is False
    client.post("/api/auth/logout")

    _login(client, "employer-block1@example.com")
    assert _send(client, seeker_id, "Thanks").status_code == 200


def test_employer_can_block_a_seeker_and_block_prevents_attachments(client):
    """The same protection applies from the employer view and to attachments."""
    _login_new_employer(client, "blockattach1")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login_new_seeker(client, "blockattach1")
    sent = _send(client, employer_id, "Hello").json()
    convo_id = sent["conversation_id"]
    client.post("/api/auth/logout")

    _login(client, "employer-blockattach1@example.com")
    assert client.post(f"/api/conversations/{convo_id}/block").status_code == 200
    client.post("/api/auth/logout")

    _login(client, "seeker-blockattach1@example.com")
    attachment = client.post(
        "/api/messages/attachment",
        data={"recipient_id": employer_id, "body": ""},
        files={"file": ("note.png", _PNG_1PX, "image/png")},
    )
    assert attachment.status_code == 403


def test_non_participant_cannot_block_conversation(client):
    _login_new_seeker(client, "blocknonpart1")
    sent = _send(client, 2, "Hello").json()
    client.post("/api/auth/logout")

    _login_new_seeker(client, "blocknonpartoutsider1")
    r = client.post(f"/api/conversations/{sent['conversation_id']}/block")
    assert r.status_code == 403


def test_delete_conversation_hides_it_only_for_requester(client):
    """
    Given a conversation between a seeker and employer
    When the seeker deletes the conversation
    Then it disappears from the seeker's inbox but the employer still sees it
    """
    _login_new_employer(client, "delconvo1")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login_new_seeker(client, "delconvo1")
    sent = _send(client, employer_id, "Hello").json()
    convo_id = sent["conversation_id"]

    r = client.delete(f"/api/conversations/{convo_id}")
    assert r.status_code == 200

    seeker_inbox = client.get("/api/conversations").json()
    assert seeker_inbox == []
    client.post("/api/auth/logout")

    _login(client, "employer-delconvo1@example.com")
    employer_inbox = client.get("/api/conversations").json()
    assert len(employer_inbox) == 1


def test_deleted_conversation_reappears_on_new_message(client):
    """
    Given a seeker deleted a conversation from their inbox
    When a new message arrives in that conversation
    Then it reappears in the seeker's inbox too (matches WhatsApp/Telegram
    "delete chat" behavior — it's not a permanent block)
    """
    _login_new_employer(client, "delconvoreappear1")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    _login_new_seeker(client, "delconvoreappear1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    sent = _send(client, employer_id, "Hello").json()
    convo_id = sent["conversation_id"]
    client.delete(f"/api/conversations/{convo_id}")
    assert client.get("/api/conversations").json() == []
    client.post("/api/auth/logout")

    _login(client, "employer-delconvoreappear1@example.com")
    _send(client, seeker_id, "Following up")
    client.post("/api/auth/logout")

    _login(client, "seeker-delconvoreappear1@example.com")
    seeker_inbox = client.get("/api/conversations").json()
    assert len(seeker_inbox) == 1


def test_cannot_delete_conversation_not_a_participant_in(client):
    """
    Given a conversation between a seeker and employer
    When an unrelated seeker tries to delete it
    Then I receive 403 Forbidden
    """
    _login_new_seeker(client, "delconvononpart1")
    sent = _send(client, 2, "Hello").json()
    convo_id = sent["conversation_id"]
    client.post("/api/auth/logout")

    _login_new_seeker(client, "delconvononpartoutsider1")
    r = client.delete(f"/api/conversations/{convo_id}")
    assert r.status_code == 403
