import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, UploadFile, File, Request, HTTPException, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from job_portal.database import get_db
from job_portal.models import Application, Job, SeekerProfile, Notification
from job_portal.routes.auth import get_current_account, get_current_account_optional, require_role
from job_portal.services.credibility import compute_credibility_score

router = APIRouter(tags=["Applications Core Engine"])
templates = Jinja2Templates(directory="UI/html")

# Mirrors TEST_EMPLOYERS in api.js. There's no Employer table yet — jobs
# only carry a numeric employer_id — so this is the single source of
# truth for turning that id into a display name on the backend. Every
# application used to be stamped with a hardcoded "ABC Technologies"
# regardless of which employer actually posted the job; this replaces
# that with a real per-job lookup.
EMPLOYER_DIRECTORY = {
    1: "ABC Technologies",
    2: "Nova Digital",
    3: "Everest Analytics",
}


def _company_name_for(job: Optional[Job]) -> str:
    if job is None:
        return "Unknown Company"
    return EMPLOYER_DIRECTORY.get(job.employer_id, f"Employer #{job.employer_id}")


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
async def get_apply_page(
    request: Request,
    job_id: int,
    account: Optional[dict] = Depends(get_current_account_optional),
    db: Session = Depends(get_db),
):
    if account is None or account["role"] != "seeker":
        # Reached by real browser navigation, not fetch() — a raw 401 JSON
        # body here would show as literal text in the user's browser, and
        # would also block apply_job.html's own requireLogin() script from
        # ever loading (the template never gets sent). Redirect directly
        # instead of relying on the frontend to handle a response it will
        # never receive.
        return RedirectResponse(url="/UI/html/login.html", status_code=303)

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="The targeted vacancy posting does not exist.")

    job.credibility_score = compute_credibility_score(job, db)

    return templates.TemplateResponse(
        request=request,
        name="apply_job.html",
        context={"job": job},
    )


@router.post("/apply")
async def handle_application(
    request: Request,
    job_id: int = Form(...),
    cover_letter: str = Form(None),
    resume: Optional[UploadFile] = File(None),
    account: Optional[dict] = Depends(get_current_account_optional),
    db: Session = Depends(get_db)
):
    if account is None or account["role"] != "seeker":
        return RedirectResponse(url="/UI/html/login.html", status_code=303)
    seeker_id = account["id"]

    job = db.query(Job).filter(Job.id == job_id).first()

    if resume and resume.filename:
        os.makedirs("uploads/resumes", exist_ok=True)
        file_path = os.path.join("uploads", "resumes", resume.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await resume.read())

    profile = db.query(SeekerProfile).filter(SeekerProfile.seeker_id == seeker_id).first()
    seeker_name = (profile.full_name if profile and profile.full_name else f"Seeker #{seeker_id}")
    seeker_email = (profile.email if profile and profile.email else f"seeker{seeker_id}@email.com")

    new_application = Application(
        seeker_id=seeker_id,
        seeker_name=seeker_name,
        job_id=job_id,
        job_title=job.title if job else "Backend Engineer",
        company_name=_company_name_for(job),
        skills=job.skills_required if job else "",
        status="Applied",
        applied_date=datetime.now().strftime("%d %B %Y"),
        cover_letter=cover_letter or "",
        email=seeker_email,
    )
    db.add(new_application)
    db.commit()

    return RedirectResponse(url="/UI/html/profile.html", status_code=303)


@router.get("/my-applications-fragment", response_class=HTMLResponse)
async def get_applications_fragment(
    request: Request,
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: Session = Depends(get_db),
):
    records = db.query(Application).filter(Application.seeker_id == seeker_id).all()

    formatted_apps = []
    for app in records:
        skills_list = _skills_list(app.job.skills_required) if app.job else _skills_list(app.skills)
        formatted_apps.append({
            "job_title": app.job.title if app.job else app.job_title,
            "company_name": _company_name_for(app.job) if app.job else (app.company_name or "Unknown Company"),
            "applied_date": app.applied_date,
            "skills": skills_list,
            "status": app.status
        })
    return templates.TemplateResponse(request=request, name="my_application_fragment.html", context={"applications": formatted_apps})


@router.get("/api/applications")
async def api_get_applications(
    seeker_id: int = Depends(require_role("seeker", "Must be logged in as a job seeker.")),
    db: Session = Depends(get_db),
):
    """Consumed by my_application.html — returns only the logged-in
    seeker's own applications; seeker_id comes from the session, never
    from the client."""
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
            "company": _company_name_for(app.job) if app.job else (app.company_name or "Unknown Company"),
            "applied_date": app.applied_date,
            "skills": skills_list,
            "status": app.status,
        })

    return JSONResponse(content=results)


@router.get("/api/employer/applications")
async def api_employer_applications(
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
):
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
async def api_applicant_detail(
    application_id: int,
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
):
    """Consumed by applicant_detail.html. Previously had NO auth check at
    all and no ownership scoping — any application id worked for anyone,
    logged in or not. Now scoped to applications belonging to a job this
    employer actually owns."""
    app = (
        db.query(Application)
        .join(Job, Application.job_id == Job.id)
        .filter(Application.id == application_id, Job.employer_id == employer_id)
        .first()
    )
    if not app:
        raise HTTPException(status_code=404, detail="Applicant record not found.")

    return JSONResponse(content={
        "id": app.id,
        "seeker_id": app.seeker_id,
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


# The pipeline has no separate "Hired" stage — "Offered" is the closest
# real signal that a position has actually been filled, so it's what
# triggers the position-filled count (and auto-close) below. See
# UI/html/applicant_detail.html's STAGES list for the full pipeline.
_POSITION_FILLED_STAGE = "Offered"


@router.post("/api/employer/applicant/{application_id}/update")
async def api_update_applicant_stage(
    application_id: int,
    body: StageUpdate = Body(...),
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
):
    """Consumed by applicant_detail.html's save button. Updates status/notes
    and, if the status actually changed, creates a Notification for the seeker.

    Also has a side effect on the job itself (Teammate A's territory):
    moving an applicant to "Offered" counts as filling one of the job's
    positions. Once positions_filled reaches positions_available, the
    listing auto-closes so it stops accepting new applicants — an employer
    hiring 1/1 shouldn't keep receiving applications for a role that's gone.

    Previously had NO auth check at all — any application id could be
    mutated by anyone, logged in or not, including the position-filled and
    auto-close side effects. Now scoped to applications belonging to a job
    this employer actually owns, same pattern as api_applicant_detail.
    """
    app = (
        db.query(Application)
        .join(Job, Application.job_id == Job.id)
        .filter(Application.id == application_id, Job.employer_id == employer_id)
        .first()
    )
    if not app:
        raise HTTPException(status_code=404, detail="Applicant record not found.")

    status_changed = app.status != body.stage
    previous_stage = app.status
    app.status = body.stage
    if body.notes is not None:
        app.notes = body.notes

    if status_changed and app.job is not None:
        if body.stage == _POSITION_FILLED_STAGE and previous_stage != _POSITION_FILLED_STAGE:
            app.job.positions_filled = min(
                app.job.positions_filled + 1, app.job.positions_available
            )
            if (
                app.job.positions_filled >= app.job.positions_available
                and app.job.status == "open"
            ):
                app.job.status = "closed"
        elif previous_stage == _POSITION_FILLED_STAGE and body.stage != _POSITION_FILLED_STAGE:
            # Applicant un-offered (e.g. rescinded) — free the position back up.
            # Note: this does NOT automatically reopen a job that auto-closed —
            # reopening is a manual "Publish" action, since silently reopening
            # a closed listing without the employer choosing to could be
            # surprising (and there's currently no "reopen a closed job"
            # button in job_management.html either — worth adding if this
            # scenario turns out to matter for your sprint).
            app.job.positions_filled = max(app.job.positions_filled - 1, 0)

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
async def api_get_notifications(
    account: dict = Depends(get_current_account),
    db: Session = Depends(get_db),
):
    """Consumed by both notifications.html (seeker) and
    employer_notifications.html (employer) — the same Notification table,
    just a different owning column depending on the logged-in role. This
    used to be a client-suppliable role/user_id combo (or a bare
    seeker_id=1 default) — now identity comes only from the session, and
    the separate /api/employer/notifications endpoint that used to exist
    purely to work around that is gone (see api_get_employer_notifications
    below, deleted)."""
    if account["role"] == "seeker":
        notif_filter = Notification.seeker_id == account["id"]
    elif account["role"] == "employer":
        notif_filter = Notification.employer_id == account["id"]
    else:
        return JSONResponse(content=[])

    records = (
        db.query(Notification)
        .filter(notif_filter)
        .order_by(Notification.created_at.desc())
        .all()
    )

    results = [
        {
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "time_ago": _humanize(n.created_at),
        }
        for n in records
    ]

    return JSONResponse(content=results)


@router.delete("/api/notifications/{notification_id}")
async def api_delete_notification(
    notification_id: int,
    account: dict = Depends(get_current_account),
    db: Session = Depends(get_db),
):
    """Remove a single notification. Works for both seeker and employer
    notifications (same Notification table, just a different owning
    column) — role and owner id now come from the session, not
    client-suppliable query params."""
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found.")

    if account["role"] not in ("seeker", "employer"):
        raise HTTPException(status_code=403, detail="Notifications are only available to seekers and employers.")
    owner_id = notif.seeker_id if account["role"] == "seeker" else notif.employer_id
    if owner_id != account["id"]:
        raise HTTPException(status_code=403, detail="Not your notification.")

    db.delete(notif)
    db.commit()
    return JSONResponse(content={"success": True})


@router.delete("/api/notifications")
async def api_clear_notifications(
    account: dict = Depends(get_current_account),
    db: Session = Depends(get_db),
):
    """Clear-all convenience — same ownership scoping as the single-delete
    endpoint above, just applied to every matching row at once."""
    if account["role"] not in ("seeker", "employer"):
        raise HTTPException(status_code=403, detail="Notifications are only available to seekers and employers.")
    column = Notification.seeker_id if account["role"] == "seeker" else Notification.employer_id
    deleted = db.query(Notification).filter(column == account["id"]).delete()
    db.commit()
    return JSONResponse(content={"success": True, "deleted": deleted})