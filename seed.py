"""
Seed script: populates the local dev database with sample jobs (across a
spread of states, salaries, and job types so the new filters have something
real to filter) plus a sample seeker profile so the recommendation engine
has data to work with.

Run from the repo root (the folder that contains src/, UI/, pyproject.toml):
    python seed.py        (PowerShell)
    python3 seed.py       (bash/Mac/Linux)

Safe to re-run — it clears existing jobs/profiles first.
"""

import sys

sys.path.insert(0, "src")

from job_portal.database import Base, SessionLocal, engine
from job_portal.models import Job, SeekerProfile

Base.metadata.create_all(bind=engine)
db = SessionLocal()

db.query(Job).delete()
db.query(SeekerProfile).delete()

db.add_all(
    [
        Job(
            employer_id=1,
            title="Backend Engineer",
            description="Build and maintain our FastAPI services, working closely with the "
            "data team on API design and performance.",
            location="Penang, Malaysia",
            state="Penang",
            salary_min=4500,
            salary_max=7000,
            job_type="Full-time",
            skills_required="Python,FastAPI,SQL",
            status="open",
            positions_available=3,
            positions_filled=1,
        ),
        Job(
            employer_id=2,
            title="Frontend Developer",
            description="Build responsive web interfaces using React, working closely with "
            "our design team to ship polished user experiences.",
            location="Remote",
            state="Remote",
            salary_min=3500,
            salary_max=5500,
            job_type="Remote",
            skills_required="JavaScript,React,CSS",
            status="open",
            positions_available=2,
            positions_filled=0,
        ),
        Job(
            employer_id=1,
            title="UI/UX Designer",
            description="Design user flows and interfaces for our job portal product, "
            "collaborating with engineering on implementation.",
            location="Kuala Lumpur, Malaysia",
            state="Kuala Lumpur",
            salary_min=4000,
            salary_max=6500,
            job_type="Full-time",
            skills_required="Figma,User Research",
            status="open",
            positions_available=1,
            positions_filled=1,
        ),
        Job(
            employer_id=3,
            title="Data Analyst Intern",
            description="Support the analytics team with SQL reporting and dashboarding "
            "using Python and Excel.",
            location="Petaling Jaya, Selangor",
            state="Selangor",
            salary_min=1500,
            salary_max=2200,
            job_type="Internship",
            skills_required="Python,SQL,Excel",
            status="open",
            positions_available=2,
            positions_filled=0,
        ),
        Job(
            employer_id=2,
            title="DevOps Contractor",
            description="Short-term contract to set up CI/CD pipelines and container "
            "infrastructure for a growing engineering team.",
            location="Johor Bahru, Johor",
            state="Johor",
            salary_min=6000,
            salary_max=9000,
            job_type="Contract",
            skills_required="Docker,Kubernetes,CI/CD",
            status="open",
            positions_available=1,
            positions_filled=0,
        ),
    ]
)

# A sample seeker profile so /api/jobs/recommended has something to match against.
db.add(
    SeekerProfile(
        seeker_id=1,
        full_name="Aisha Rahman",
        email="aisha.rahman@example.com",
        phone="012-345 6789",
        bio="Backend-leaning full-stack developer with 2 years of experience "
        "building APIs and internal tools. Enjoys clean code and clear docs.",
        skills="Python,FastAPI,SQL,Docker",
    )
)

db.commit()
print(f"Seeded {db.query(Job).count()} jobs and {db.query(SeekerProfile).count()} seeker profile(s).")
