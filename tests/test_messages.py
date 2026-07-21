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