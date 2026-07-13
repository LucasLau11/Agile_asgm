import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, UploadFile, File, Request, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from job_portal.database import get_db
from job_portal.models import Application, Job, SeekerProfile, Notification
from services.credibility import compute_credibility_score

router = APIRouter(tags=["Applications Core Engine"])
templates = Jinja2Templates(directory="UI/html")


def _skills_list(csv_str: Optional[str]) -> list[str]:
    """Split a comma-separated skills string into a clean list (shared helper)."""
    if not csv_str:
        return []
    return [s.strip() for s in csv_str.split(",") if s.strip()]


def _humanize(dt: Optional[datetime]) -> str:
    """Turn a datetime into a rough 'x hours ago' style string."""
    if not dt:
        return ""
    delta = datetime.utcnow() - dt
    seconds = delta.total_seconds()
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        mins = int(seconds // 60)
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(seconds // 86400)
    if days == 1:
        return "Yesterday"
    return f"{days} days ago"


# Seeker: apply for a job  


@router.get("/apply", response_class=HTMLResponse)
async def get_apply_page(request: Request, job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="The targeted vacancy posting does not exist.")

    job.credibility_score = compute_credibility_score(job, db)

    return templates.TemplateResponse(
        request=request,
        name="apply_job.html",
        context={"job": job}
    )


@router.post("/apply")
async def handle_application(
    request: Request,
    job_id: int = Form(...),
    cover_letter: str = Form(None),
    resume: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    job = db.query(Job).filter(Job.id == job_id).first()

    if resume and resume.filename:
        os.makedirs("uploads/resumes", exist_ok=True)
        file_path = os.path.join("uploads", "resumes", resume.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await resume.read())

    new_application = Application(
        seeker_id=1,  # Default Seeker ID (Aisha) — no auth system yet
        seeker_name="Aisha Rahman",
        job_id=job_id,
        job_title=job.title if job else "Backend Engineer",
        company_name="ABC Technologies",
        skills=job.skills_required if job else "",
        status="Applied",
        applied_date=datetime.now().strftime("%d %B %Y"),
        cover_letter=cover_letter or "",
        email="aisha@email.com",
    )
    db.add(new_application)
    db.commit()

    return RedirectResponse(url="/UI/html/profile.html", status_code=303)


@router.get("/my-applications-fragment", response_class=HTMLResponse)
async def get_applications_fragment(request: Request, db: Session = Depends(get_db)):
    records = db.query(Application).filter(Application.seeker_id == 1).all()

    formatted_apps = []
    for app in records:
        skills_list = _skills_list(app.job.skills_required) if app.job else _skills_list(app.skills)
        formatted_apps.append({
            "job_title": app.job.title if app.job else app.job_title,
            "company_name": app.company_name or "ABC Technologies",
            "applied_date": app.applied_date,
            "skills": skills_list,
            "status": app.status
        })
    return templates.TemplateResponse(request=request, name="my_application_fragment.html", context={"applications": formatted_apps})


@router.get("/api/applications")
async def api_get_applications(seeker_id: int = Query(1), db: Session = Depends(get_db)):
    """Consumed by my_application.html. This was the missing endpoint causing
    'Failed to pull database entries'."""
    records = (
        db.query(Application)
        .filter(Application.seeker_id == seeker_id)
        .order_by(Application.id.desc())
        .all()
    )

    results = []
    for app in records:
        skills_list = _skills_list(app.job.skills_required) if app.job else _skills_list(app.skills)
        results.append({
            "id": app.id,
            "job_title": app.job.title if app.job else app.job_title,
            "company": app.company_name or "ABC Technologies",
            "applied_date": app.applied_date,
            "skills": skills_list,
            "status": app.status,
        })

    return JSONResponse(content=results)


@router.get("/api/employer/applications")
async def api_employer_applications(employer_id: int = Query(1), db: Session = Depends(get_db)):
    """Consumed by employer_applications.html."""
    records = (
        db.query(Application)
        .join(Job, Application.job_id == Job.id)
        .filter(Job.employer_id == employer_id)
        .order_by(Application.id.desc())
        .all()
    )

    results = []
    for app in records:
        results.append({
            "id": app.id,
            "seeker": app.seeker_name,
            "email": app.email,
            "job_title": app.job.title if app.job else app.job_title,
            "status": app.status,
            "skills": _skills_list(app.skills) or (_skills_list(app.job.skills_required) if app.job else []),
            "applied_date": app.applied_date,
        })

    return JSONResponse(content=results)


@router.get("/api/employer/applicant/{application_id}")
async def api_applicant_detail(application_id: int, db: Session = Depends(get_db)):
    """Consumed by applicant_detail.html."""
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Applicant record not found.")

    return JSONResponse(content={
        "id": app.id,
        "seeker": app.seeker_name,
        "email": app.email,
        "job_title": app.job.title if app.job else app.job_title,
        "status": app.status,
        "skills": _skills_list(app.skills) or (_skills_list(app.job.skills_required) if app.job else []),
        "cover_letter": app.cover_letter or "No cover letter provided.",
        "notes": app.notes or "",
    })


class StageUpdate(BaseModel):
    stage: str
    notes: Optional[str] = None


@router.post("/api/employer/applicant/{application_id}/update")
async def api_update_applicant_stage(
    application_id: int,
    body: StageUpdate = Body(...),
    db: Session = Depends(get_db),
):
    """Consumed by applicant_detail.html's save button. Updates status/notes
    and, if the status actually changed, creates a Notification for the seeker."""
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Applicant record not found.")

    status_changed = app.status != body.stage
    app.status = body.stage
    if body.notes is not None:
        app.notes = body.notes

    if status_changed:
        job_title = app.job.title if app.job else app.job_title
        notif = Notification(
            seeker_id=app.seeker_id,
            application_id=app.id,
            title=f"Application moved to {body.stage}",
            message=f"Your application for {job_title} has progressed to the {body.stage} stage.",
        )
        db.add(notif)

    db.commit()
    return JSONResponse(content={"success": True, "status": app.status})


@router.get("/api/notifications")
async def api_get_notifications(seeker_id: int = Query(1), db: Session = Depends(get_db)):
    """Consumed by notifications.html."""
    records = (
        db.query(Notification)
        .filter(Notification.seeker_id == seeker_id)
        .order_by(Notification.created_at.desc())
        .all()
    )

    results = [
        {
            "title": n.title,
            "message": n.message,
            "time_ago": _humanize(n.created_at),
        }
        for n in records
    ]

    return JSONResponse(content=results)