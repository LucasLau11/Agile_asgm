"""
Authorization tests for the messaging retrofit (phase 2e) — proves every
endpoint's identity comes only from the session, never a client-suppliable
role/id. Business-logic behavior (blocking, edit windows, deletion scopes)
is already covered in tests/test_messages.py; this file is specifically
about the identity/authorization property, following the pattern phase 2d
used for its own auth-focused coverage.
"""

from job_portal.models import Conversation, Message


def _login_new_seeker(client, tag, full_name="Test Seeker"):
    for index in (1, 2):
        response = client.post("/api/auth/register/employer", json={
            "company_name": f"Contact Employer {tag}-{index}",
            "email": f"contact-employer-msgauth-{tag}-{index}@example.com",
            "password": "correcthorse",
        })
        assert response.status_code == 201, response.text
        client.post("/api/auth/logout")
    client.post("/api/auth/register/seeker", json={
        "full_name": full_name,
        "email": f"seeker-msgauth-{tag}@example.com",
        "password": "correcthorse",
    })


def _login_new_employer(client, tag, company_name="Test Co"):
    for index, word in ((1, "One"), (2, "Two")):
        response = client.post("/api/auth/register/seeker", json={
            "full_name": f"Contact Seeker {word}",
            "email": f"contact-seeker-msgauth-{tag}-{index}@example.com",
            "password": "correcthorse",
        })
        assert response.status_code == 201, response.text
        client.post("/api/auth/logout")
    response = client.post("/api/auth/register/employer", json={
        "company_name": company_name,
        "email": f"employer-msgauth-{tag}@example.com",
        "password": "correcthorse",
    })
    assert response.status_code == 201, response.text


def _seed_conversation(db_session, seeker_id, employer_id):
    convo = Conversation(seeker_id=seeker_id, employer_id=employer_id)
    db_session.add(convo)
    db_session.commit()
    db_session.refresh(convo)
    return convo


def _seed_message(db_session, convo, sender_role, sender_id, body="Hello"):
    from job_portal.services.message_crypto import encrypt_text

    message = Message(
        conversation_id=convo.id, sender_role=sender_role, sender_id=sender_id,
        body=encrypt_text(body),
    )
    db_session.add(message)
    db_session.commit()
    db_session.refresh(message)
    return message


# ---------------------------------------------------------------------------
# POST /api/messages
# ---------------------------------------------------------------------------


def test_send_message_requires_login(client):
    r = client.post("/api/messages", json={"recipient_id": 1, "body": "hi"})
    assert r.status_code == 401


def test_message_contacts_are_real_registered_accounts(client):
    _login_new_employer(client, "realcontact", company_name="Real Contact Sdn Bhd")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")
    _login_new_seeker(client, "contactviewer")

    response = client.get("/api/messages/contacts")
    assert response.status_code == 200
    assert {contact["id"]: contact["name"] for contact in response.json()}[employer_id] == "Real Contact Sdn Bhd"


def test_cannot_message_nonexistent_recipient(client):
    _login_new_seeker(client, "missingrecipient")
    response = client.post("/api/messages", json={
        "recipient_id": 999999, "body": "This must not create an orphan conversation."
    })
    assert response.status_code == 404


def test_conversation_uses_real_employer_name(client):
    _login_new_employer(client, "realname", company_name="Database Name Sdn Bhd")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")
    _login_new_seeker(client, "realname")
    client.post("/api/messages", json={"recipient_id": employer_id, "body": "Hello"})

    conversations = client.get("/api/conversations").json()
    assert conversations[0]["other_party_name"] == "Database Name Sdn Bhd"


def test_send_message_uses_session_identity_not_client_supplied(client, db_session):
    """
    Given a seeker is logged in
    When they POST /api/messages (there's no sender_role/sender_id field
    left on the request at all — MessageCreate dropped them)
    Then the created message is genuinely attributed to THEM, not
    whatever the request might have tried to claim.
    """
    _login_new_seeker(client, "send1")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]

    r = client.post("/api/messages", json={"recipient_id": 1, "body": "Hi there"})
    assert r.status_code == 200
    body = r.json()
    assert body["sender_role"] == "seeker"
    assert body["sender_id"] == seeker_id


# ---------------------------------------------------------------------------
# GET /api/conversations/{id}/messages, GET /api/messages/{id}/attachment,
# PUT /api/messages/{id}, DELETE /api/messages/{id} — cross-conversation
# isolation
# ---------------------------------------------------------------------------


def test_third_party_cannot_read_a_conversation_they_are_not_in(client, db_session):
    _login_new_seeker(client, "victimA")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "victimB")
    employer_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")

    convo = _seed_conversation(db_session, seeker_id, employer_id)

    _login_new_seeker(client, "outsider")
    r = client.get(f"/api/conversations/{convo.id}/messages")
    assert r.status_code == 403


def test_non_sender_cannot_edit_a_message(client, db_session):
    _login_new_seeker(client, "editvictim")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "editowner")
    employer_id = client.get("/api/auth/me").json()["id"]

    convo = _seed_conversation(db_session, seeker_id, employer_id)
    message = _seed_message(db_session, convo, "employer", employer_id)
    client.post("/api/auth/logout")

    _login_new_seeker(client, "editattacker")
    seeker2_id = client.get("/api/seekers/me").json()["seeker_id"]
    # The attacker isn't even a participant in this conversation, so this
    # should 403 at the participant check before it ever reaches the
    # sender check.
    r = client.put(f"/api/messages/{message.id}", json={"body": "hacked"})
    assert r.status_code == 403


def test_non_sender_participant_cannot_delete_for_everyone(client, db_session):
    """
    Given a seeker and employer share a conversation, and the EMPLOYER sent
    a message
    When the SEEKER (a real participant, just not the sender) tries to
    delete it with scope=everyone
    Then it's rejected — sender-only, even for a fellow participant.
    """
    _login_new_seeker(client, "delparticipant")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "delsender")
    employer_id = client.get("/api/auth/me").json()["id"]
    convo = _seed_conversation(db_session, seeker_id, employer_id)
    message = _seed_message(db_session, convo, "employer", employer_id)
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={
        "email": "seeker-msgauth-delparticipant@example.com", "password": "correcthorse",
    })
    r = client.delete(f"/api/messages/{message.id}?scope=everyone")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/conversations, POST /api/conversations/find-or-create,
# block/unblock, delete conversation
# ---------------------------------------------------------------------------


def test_list_conversations_requires_login(client):
    r = client.get("/api/conversations")
    assert r.status_code == 401


def test_list_conversations_only_shows_own(client, db_session):
    _login_new_seeker(client, "listmine")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "listother")
    employer_id = client.get("/api/auth/me").json()["id"]
    _seed_conversation(db_session, seeker_id, employer_id)
    # A second, unrelated conversation this employer isn't part of.
    _login_new_seeker(client, "listunrelated")
    other_seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    _login_new_employer(client, "listunrelated2")
    other_employer_id = client.get("/api/auth/me").json()["id"]
    _seed_conversation(db_session, other_seeker_id, other_employer_id)
    client.post("/api/auth/logout")

    client.post("/api/auth/login", json={
        "email": "employer-msgauth-listother@example.com", "password": "correcthorse",
    })
    r = client.get("/api/conversations")
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1


def test_third_party_cannot_block_a_conversation_they_are_not_in(client, db_session):
    _login_new_seeker(client, "blockvictimA")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")
    _login_new_employer(client, "blockvictimB")
    employer_id = client.get("/api/auth/me").json()["id"]
    convo = _seed_conversation(db_session, seeker_id, employer_id)
    client.post("/api/auth/logout")

    _login_new_seeker(client, "blockoutsider")
    r = client.post(f"/api/conversations/{convo.id}/block")
    assert r.status_code == 403


def test_third_party_cannot_delete_a_conversation_they_are_not_in(client, db_session):
    _login_new_seeker(client, "delconvoA")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")
    _login_new_employer(client, "delconvoB")
    employer_id = client.get("/api/auth/me").json()["id"]
    convo = _seed_conversation(db_session, seeker_id, employer_id)
    client.post("/api/auth/logout")

    _login_new_seeker(client, "delconvooutsider")
    r = client.delete(f"/api/conversations/{convo.id}")
    assert r.status_code == 403


def test_find_or_create_conversation_requires_login(client):
    r = client.post("/api/conversations/find-or-create?other_id=1")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Interview invitations — employer-only send/reschedule/cancel,
# seeker-only response
# ---------------------------------------------------------------------------


def test_send_interview_invite_requires_employer_login(client):
    r = client.post(
        "/api/messages/interview-invite?seeker_id=1",
        json={"scheduled_at": "2026-09-01T10:00:00", "duration_minutes": 30, "mode": "video"},
    )
    assert r.status_code == 401


def test_seeker_cannot_send_interview_invite(client):
    _login_new_seeker(client, "notemployer")
    r = client.post(
        "/api/messages/interview-invite?seeker_id=1",
        json={"scheduled_at": "2026-09-01T10:00:00", "duration_minutes": 30, "mode": "video"},
    )
    assert r.status_code == 401


def test_employer_can_send_interview_invite_using_session_identity(client, db_session):
    _login_new_seeker(client, "invitetarget")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "inviter")
    r = client.post(
        f"/api/messages/interview-invite?seeker_id={seeker_id}",
        json={"scheduled_at": "2026-09-01T10:00:00", "duration_minutes": 30, "mode": "video"},
    )
    assert r.status_code == 200
    assert r.json()["sender_role"] == "employer"


def test_employer_cannot_respond_to_interview_invite(client, db_session):
    _login_new_seeker(client, "respondtarget")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "responder")
    r = client.post(
        f"/api/messages/interview-invite?seeker_id={seeker_id}",
        json={"scheduled_at": "2026-09-01T10:00:00", "duration_minutes": 30, "mode": "video"},
    )
    message_id = r.json()["id"]

    r = client.post(f"/api/messages/{message_id}/interview-response", json={"response": "accepted"})
    assert r.status_code == 401


def test_non_sender_employer_cannot_reschedule_or_cancel_interview(client, db_session):
    _login_new_seeker(client, "reschedtarget")
    seeker_id = client.get("/api/seekers/me").json()["seeker_id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "reschedowner")
    r = client.post(
        f"/api/messages/interview-invite?seeker_id={seeker_id}",
        json={"scheduled_at": "2026-09-01T10:00:00", "duration_minutes": 30, "mode": "video"},
    )
    message_id = r.json()["id"]
    client.post("/api/auth/logout")

    _login_new_employer(client, "reschedattacker")
    r = client.put(
        f"/api/messages/{message_id}/interview-reschedule",
        json={"scheduled_at": "2026-09-02T10:00:00", "duration_minutes": 30, "mode": "video"},
    )
    assert r.status_code == 403

    r = client.post(f"/api/messages/{message_id}/interview-cancel")
    assert r.status_code == 403
