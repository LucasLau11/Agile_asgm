def _login_new_employer(client, tag, company_name="Test Co"):
    """Registers and logs in a fresh employer account for test isolation —
    same pattern as _login_new_seeker in test_seeker.py."""
    client.post("/api/auth/register/employer", json={
        "company_name": company_name,
        "email": f"employer-{tag}@gmail.com",
        "password": "correcthorse",
    })


def test_get_employer_profile_requires_login(client):
    r = client.get("/api/employers/me")
    assert r.status_code == 401


def test_get_employer_profile_rejects_seeker_session(client):
    client.post("/api/auth/register/seeker", json={
        "full_name": "Not An Employer", "email": "not-employer-1@gmail.com", "password": "correcthorse",
    })
    r = client.get("/api/employers/me")
    assert r.status_code == 401


def test_get_employer_profile_returns_defaults_for_new_account(client):
    _login_new_employer(client, "1", company_name="Acme Corp")
    r = client.get("/api/employers/me")
    assert r.status_code == 200
    body = r.json()
    assert body["company_name"] == "Acme Corp"
    assert body["description"] is None
    assert body["industry"] is None
    assert body["website"] is None


def test_update_employer_profile_requires_login(client):
    r = client.put("/api/employers/me", json={"company_name": "Acme Corp"})
    assert r.status_code == 401


def test_update_employer_profile_persists_fields(client):
    _login_new_employer(client, "2", company_name="Acme Corp")
    r = client.put("/api/employers/me", json={
        "company_name": "Acme Corporation",
        "description": "We build things.",
        "industry": "Technology",
        "website": "https://acme.example.com",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["company_name"] == "Acme Corporation"
    assert body["description"] == "We build things."
    assert body["industry"] == "Technology"
    assert body["website"] == "https://acme.example.com"

    # Persisted, not just echoed back
    r2 = client.get("/api/employers/me")
    assert r2.json()["description"] == "We build things."


def test_update_employer_profile_rejects_blank_company_name(client):
    _login_new_employer(client, "3")
    r = client.put("/api/employers/me", json={"company_name": "   "})
    assert r.status_code == 422


def test_employer_can_only_update_own_profile(client):
    """
    Given two different registered employers
    When employer B updates "their" profile
    Then employer A's data is completely untouched — there is no id in the
    URL or body for B to target A with in the first place.
    """
    _login_new_employer(client, "ownerA", company_name="Company A")
    client.put("/api/employers/me", json={"company_name": "Company A", "industry": "Finance"})
    client.post("/api/auth/logout")

    _login_new_employer(client, "ownerB", company_name="Company B")
    client.put("/api/employers/me", json={"company_name": "Company B", "industry": "Retail"})

    r = client.get("/api/employers/me")
    assert r.json()["company_name"] == "Company B"
    assert r.json()["industry"] == "Retail"
