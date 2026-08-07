"""
Seed script: creates the single admin account from environment variables.
Safe to re-run — a no-op if the admin email already exists.

Usage:
  ADMIN_SEED_PASSWORD=your-password py seed_admin.py
  (optionally also set ADMIN_SEED_EMAIL to override the default)
"""

import os
import sys

sys.path.insert(0, "src")

from job_portal.database import Base, SessionLocal, engine
from job_portal.models import Admin
from job_portal.services.auth import hash_password

ADMIN_EMAIL = os.environ.get("ADMIN_SEED_EMAIL", "admin@jobportal.local")
ADMIN_PASSWORD = os.environ.get("ADMIN_SEED_PASSWORD")

if not ADMIN_PASSWORD:
    print(
        "ADMIN_SEED_PASSWORD is not set — refusing to create an admin account "
        "with no password. Set it and re-run, e.g.:"
    )
    print("  ADMIN_SEED_PASSWORD=your-password py seed_admin.py")
    sys.exit(1)

Base.metadata.create_all(bind=engine)
db = SessionLocal()

existing = db.query(Admin).filter(Admin.email == ADMIN_EMAIL).first()
if existing:
    print(f"Admin account already exists for {ADMIN_EMAIL} — nothing to do.")
else:
    admin = Admin(email=ADMIN_EMAIL, hashed_password=hash_password(ADMIN_PASSWORD))
    db.add(admin)
    db.commit()
    print(f"Created admin account for {ADMIN_EMAIL}.")

db.close()
