"""
Database setup for the Job Portal app.

- In production, set DATABASE_URL to your Supabase Postgres connection string
  (Supabase dashboard -> Project Settings -> Database -> Connection string).
- For local dev and pytest, we fall back to a local SQLite file so nobody
  needs a live Supabase connection just to run tests.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./job_portal.db")

# SQLite needs this connect_arg when used with FastAPI's threaded requests.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session and always closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
