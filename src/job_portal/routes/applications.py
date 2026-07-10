import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Form, UploadFile, File, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from job_portal.database import get_db
from job_portal.models import Application, Job, SeekerProfile

router = APIRouter(tags=["Applications Core Engine"])
templates = Jinja2Templates(directory="UI/html")

@router.get("/apply", response_class=HTMLResponse)
async def get_apply_page(request: Request, job_id: int, db: Session = Depends(get_db)):
    """Renders dynamically calculated positions based on user parameters instead of static values."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="The targeted vacancy posting does not exist.")
    
    return templates.TemplateResponse(
        request=request, 
        name="apply_job.html", 
        context={"job": job}
    )

from datetime import datetime

@router.post("/apply")
async def handle_application(
    request: Request,
    job_id: int = Form(...),
    cover_letter: str = Form(None),
    resume: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """Saves dynamic applications linked with seeker profiles and positions."""
    # 1. Save uploaded resume if provided
    if resume and resume.filename:
        os.makedirs("uploads/resumes", exist_ok=True)
        file_path = os.path.join("uploads", "resumes", resume.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await resume.read())

    # 2. Log database entry linking to peer's Job model
    new_application = Application(
        seeker_id=1, # Default Seeker ID (Aisha)
        seeker_name="Aisha Rahman",
        job_id=job_id,
        status="Applied",
        applied_date=datetime.now().strftime("%d %B %Y"),
        cover_letter=cover_letter or "",
        email=""
    )
    db.add(new_application)
    db.commit()

    # Redirect directly to profile section to view submitted applications tracker
    return RedirectResponse(url="/UI/html/profile.html", status_code=303)

@router.get("/my-applications-fragment", response_class=HTMLResponse)
async def get_applications_fragment(request: Request, db: Session = Depends(get_db)):
    """Yields clean tracking sub-cards cleanly injected underneath Profile sections."""
    records = db.query(Application).filter(Application.seeker_id == 1).all()
    
    formatted_apps = []
    for app in records:
        # Peer verification integration: Extract clean dynamic fields straight from live model relationship rows
        skills_list = [s.strip() for s in app.job.skills_required] if hasattr(app.job, "skills_required") and app.job.skills_required else []
        
        formatted_apps.append({
            "job_title": app.job.title if app.job else "Unknown Position",
            "company_name": "ABC Technologies",  # Fallback corporate string mapper
            "applied_date": app.applied_date,
            "skills": skills_list,
            "status": app.status
        })
    return templates.TemplateResponse(request=request, name="my_application_fragment.html", context={"applications": formatted_apps})