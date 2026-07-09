"""
Shared pytest fixtures for Teammate B's tests.

We point DATABASE_URL at a throwaway SQLite file *before* importing the app,
so tests never touch the real Supabase database. Tables are created fresh
and dropped after every test so tests stay independent (mirrors the
`reset_db()` pattern used in the tutor's demo repo).
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_job_portal.db"

import pytest
from fastapi.testclient import TestClient

from job_portal.database import Base, SessionLocal, engine
from job_portal.main import app
from job_portal.models import Job


@pytest.fixture
def db_session():
    """Fresh tables for every test, dropped afterwards."""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session):
    """TestClient sharing the same fresh DB as db_session."""
    return TestClient(app)


@pytest.fixture
def sample_job(db_session):
    """A ready-made job posting for tests that need one to already exist."""
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
