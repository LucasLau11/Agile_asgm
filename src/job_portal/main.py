import os
import sys

# Ensure python runtime environment resolves packages seamlessly across cross-mounted sub-folders
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from job_portal.database import Base, engine
from job_portal.routes.seeker import router as seeker_router
from job_portal.routes.applications import router as applications_router  
from job_portal.routes.employer import router as employer_router

app = FastAPI(title="Job Portal Architecture", version="0.1.0")

Base.metadata.create_all(bind=engine)

app.include_router(seeker_router)
app.include_router(applications_router)  
app.include_router(employer_router)

app.mount("/UI", StaticFiles(directory="UI"), name="UI")

os.makedirs("uploads/resumes", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")