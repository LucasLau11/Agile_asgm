"""
FastAPI app entrypoint.

Teammates A and C: import and `include_router(...)` your own router here
too, following the same pattern as `seeker_router` below. Please only add
your own line — don't reformat this file when merging branches.
"""

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from job_portal.database import Base, engine
from job_portal.routes.seeker import router as seeker_router

app = FastAPI(title="Job Portal", version="0.1.0")

# Sprint 1: auto-create tables on startup so nobody needs to run migrations
# manually yet. Replace with Alembic migrations before Sprint 3.
Base.metadata.create_all(bind=engine)

app.include_router(seeker_router)
# app.include_router(jobs_router)           # Teammate A adds this
# app.include_router(applications_router)   # Teammate C adds this

# Serve the plain HTML/CSS/JS frontend from /UI/*
# (matches the UI/html + UI/css folder structure already in the repo)
app.mount("/UI", StaticFiles(directory="UI"), name="UI")

# Serve uploaded resumes so the frontend can preview/download them.
# Must exist before mounting, since StaticFiles errors on a missing folder.
os.makedirs("uploads/resumes", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
