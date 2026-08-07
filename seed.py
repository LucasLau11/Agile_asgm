"""
Seed script: populates the local dev database with sample jobs (across a
spread of states, salaries, and job types so the new filters have something
real to filter) plus a sample seeker profile so the recommendation engine
has data to work with.
"""

import sys

sys.path.insert(0, "src")

# Importing job_portal.main runs Base.metadata.create_all() and every
# _ensure_columns() migration as import-time side effects (the same thing
# that happens on every server startup) — this makes the script safe to
# run directly against a database created before this feature existed,
# without requiring the server to have been started first.
import job_portal.main  # noqa: F401

from job_portal.database import Base, SessionLocal, engine
from job_portal.models import Employer, Job, SeekerProfile, Session
from job_portal.services.auth import hash_password

# Fixed test password for every seeded account, printed at the end of this
# script's output so it's discoverable without separate docs.
TEST_PASSWORD = "password123"

Base.metadata.create_all(bind=engine)
db = SessionLocal()

db.query(Job).delete()
db.query(SeekerProfile).delete()
db.query(Employer).delete()
db.query(Session).delete()

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

# A sample seeker profile so /api/jobs/recommended has something to match
# against, and so it can log in (see TEST_PASSWORD above).
db.add(
    SeekerProfile(
        seeker_id=1,
        full_name="Aisha Rahman",
        email="aisha.rahman@example.com",
        phone="012-345 6789",
        bio="Backend-leaning full-stack developer with 2 years of experience "
        "building APIs and internal tools. Enjoys clean code and clear docs.",
        skills="Python,FastAPI,SQL,Docker",
        hashed_password=hash_password(TEST_PASSWORD),
        status="active",
    )
)

# Real Employer accounts for the employer_ids already referenced by the
# seeded jobs above (1, 2, 3) and by EMPLOYER_DIRECTORY in
# routes/applications.py — same names, so existing display logic that
# still reads EMPLOYER_DIRECTORY stays consistent with these real rows.
db.add_all(
    [
        Employer(
            id=1,
            company_name="ABC Technologies",
            email="employer1@example.com",
            hashed_password=hash_password(TEST_PASSWORD),
            status="active",
        ),
        Employer(
            id=2,
            company_name="Nova Digital",
            email="employer2@example.com",
            hashed_password=hash_password(TEST_PASSWORD),
            status="active",
        ),
        Employer(
            id=3,
            company_name="Everest Analytics",
            email="employer3@example.com",
            hashed_password=hash_password(TEST_PASSWORD),
            status="active",
        ),
    ]
)

db.commit()
print(
    f"Seeded {db.query(Job).count()} jobs, {db.query(SeekerProfile).count()} seeker profile(s), "
    f"and {db.query(Employer).count()} employer account(s)."
)
print(f'Test password for every seeded account: "{TEST_PASSWORD}"')
print("Seeded logins: aisha.rahman@example.com, employer1@example.com, employer2@example.com, employer3@example.com")
