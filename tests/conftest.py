import os

os.environ["DATABASE_URL"] = "sqlite:///./test_job_portal.db"

import pytest
from fastapi.testclient import TestClient

from job_portal.database import Base, SessionLocal, engine
from job_portal.main import app
from job_portal.models import Job


def pytest_report_teststatus(report, config):
    if report.when == "call":
        if report.passed:
            return "passed", ".", ("✔️", {"green": True})
        if report.failed:
            return "failed", "F", ("❌", {"red": True})
        if report.skipped:
            return "skipped", "s", ("⚠️", {"yellow": True})
    return None


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session):
    return TestClient(app)


@pytest.fixture
def sample_job(db_session):
    job = Job(
        employer_id=1,
        title="Backend Engineer",
        description="Build and maintain our FastAPI services. " * 3,
        location="Penang, Malaysia",
        skills_required="Python,FastAPI,SQL",
        status="open",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job