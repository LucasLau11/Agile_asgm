import io

from job_portal.models import Admin, Employer, Job
from job_portal.services.auth import hash_password


def _register_employer(client, tag="verification"):
    response = client.post("/api/auth/register/employer", json={
        "company_name": "Verified Candidate Sdn Bhd",
        "email": f"{tag}@gmail.com",
        "password": "correcthorse",
    })
    assert response.status_code == 201
    return response.json()["id"]


def _login_admin(client, db_session):
    client.post("/api/auth/logout")
    db_session.add(Admin(email="verification-admin@gmail.com", hashed_password=hash_password("correcthorse")))
    db_session.commit()
    assert client.post("/api/auth/login", json={
        "email": "verification-admin@gmail.com", "password": "correcthorse",
    }).status_code == 200


def test_employer_document_review_approval_and_badge(client, db_session):
    employer_id = _register_employer(client)
    upload = client.post(
        "/api/employers/me/verification-document",
        data={"registration_number": "202601234567"},
        files={"file": ("ssm.pdf", io.BytesIO(b"%PDF-1.4 valid registration"), "application/pdf")},
    )
    assert upload.status_code == 201
    assert upload.json()["verification_status"] == "pending"

    job = Job(employer_id=employer_id, title="Audited Role", description="A legitimate role", status="open")
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    _login_admin(client, db_session)
    pending = client.get("/api/admin/employers/pending")
    assert pending.status_code == 200
    assert [item["id"] for item in pending.json()] == [employer_id]
    document = client.get(f"/api/admin/employers/{employer_id}/verification-document")
    assert document.status_code == 200
    assert document.headers["content-type"].startswith("application/pdf")
    assert document.headers["content-disposition"].startswith("inline;")
    approved = client.post(f"/api/admin/employers/{employer_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["verification_status"] == "approved"

    visible_job = client.get(f"/api/jobs/{job.id}").json()
    assert visible_job["employer_verified"] is True
    assert visible_job["employer_name"] == "Verified Candidate Sdn Bhd"


def test_admin_search_rejection_and_statistics(client, db_session):
    employer_id = _register_employer(client, "searchable-company")
    client.post(
        "/api/employers/me/verification-document",
        data={"registration_number": "SSM-SEARCH-99"},
        files={"file": ("ssm.pdf", io.BytesIO(b"%PDF-1.4 registration"), "application/pdf")},
    )
    _login_admin(client, db_session)

    search = client.get("/api/admin/employers", params={"search": "SSM-SEARCH"})
    assert search.status_code == 200
    assert [item["id"] for item in search.json()] == [employer_id]
    detail = client.get(f"/api/admin/employers/{employer_id}")
    assert detail.json()["company_name"] == "Verified Candidate Sdn Bhd"

    rejected = client.post(f"/api/admin/employers/{employer_id}/reject", json={"reason": "SSM details do not match."})
    assert rejected.status_code == 200
    assert rejected.json()["verification_status"] == "rejected"
    stats = client.get("/api/admin/statistics").json()
    assert stats["employers"] == 1
    assert stats["pending_verifications"] == 0
