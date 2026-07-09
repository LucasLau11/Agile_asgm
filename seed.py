"""
Seed script: populates the local dev database with sample jobs so the
frontend has something real to display while Teammate A's create-job
endpoint isn't built yet.

Run from the repo root (the folder that contains src/, UI/, pyproject.toml):
    PYTHONPATH=src python3 seed.py

Safe to re-run — it clears existing jobs first.
"""

import sys

sys.path.insert(0, "src")

from job_portal.database import Base, SessionLocal, engine
from job_portal.models import Job

Base.metadata.create_all(bind=engine)
db = SessionLocal()

db.query(Job).delete()
db.add_all(
    [
        Job(
            employer_id=1,
            title="Backend Engineer",
            description="Build and maintain our FastAPI services, working closely with the "
            "data team on API design and performance.",
            location="Penang, Malaysia",
            skills_required="Python,FastAPI,SQL",
            status="open",
        ),
        Job(
            employer_id=2,
            title="Frontend Developer",
            description="Short desc.",
            location="Remote",
            skills_required="",
            status="open",
        ),
        Job(
            employer_id=1,
            title="UI/UX Designer",
            description="Design user flows and interfaces for our job portal product, "
            "collaborating with engineering on implementation.",
            location="Kuala Lumpur, Malaysia",
            skills_required="Figma,User Research",
            status="open",
        ),
    ]
)
db.commit()
print(f"Seeded {db.query(Job).count()} jobs into the database.")
