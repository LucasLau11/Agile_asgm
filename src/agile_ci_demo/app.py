import os
from typing import Dict, List, Any, Optional
from fastapi import FastAPI, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Agile CI Demo", version="0.1.0")

# --- Setup Paths for your UI folder structure ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
UI_DIR = os.path.join(BASE_DIR, "UI")

# Mount CSS folder
app.mount("/UI/css", StaticFiles(directory=os.path.join(UI_DIR, "css")), name="css")

# Point Jinja2 templates to your HTML directory
templates = Jinja2Templates(directory=os.path.join(UI_DIR, "html"))


# --- Shared Mock Database (Central Applications Tracker) ---
# Seeds the database with your specific original records so everything matches!
applications_db: List[Dict[str, Any]] = [
    {
        "id": 1,
        "seeker": "John Tan",
        "email": "john.tan@email.com",
        "job_title": "Backend Engineer",
        "company": "ABC Technologies",
        "skills": ["Python", "FastAPI", "SQL"],
        "status": "Screening",
        "applied_date": "10 July 2026",
        "cover_letter": "Hi, I have 2 years of experience working with Python APIs.",
        "experience": "2 years Software Development Experience",
        "notes": ""
    },
    {
        "id": 2,
        "seeker": "Jane Lim",
        "email": "jane.lim@email.com",
        "job_title": "Frontend Developer",
        "company": "XYZ Solutions",
        "skills": ["React", "JavaScript"],
        "status": "Interview",
        "applied_date": "8 July 2026",
        "cover_letter": "Excited to combine backend logic with modern frontends.",
        "experience": "3 years Frontend Experience",
        "notes": ""
    },
    {
        "id": 3,
        "seeker": "David Wong",
        "email": "david.wong@email.com",
        "job_title": "UI/UX Designer",
        "company": "Creative Studio",
        "skills": ["Figma", "Wireframe"],
        "status": "Rejected",
        "applied_date": "5 July 2026",
        "cover_letter": "Passionate about creating accessible user interfaces.",
        "experience": "1 year UI Design Intern Experience",
        "notes": ""
    }
]


# --- Seeker Application Routes ---

@app.get("/apply", response_class=HTMLResponse)
async def get_apply_page(request: Request):
    """Renders the apply job page view form."""
    return templates.TemplateResponse(request=request, name="apply_job.html")


@app.post("/apply")
async def handle_application(
    request: Request,
    cover_letter: str = Form(None), 
    resume: Optional[UploadFile] = File(None)
):
    """Handles applicant submissions safely and updates the centralized listing database."""
    if resume and hasattr(resume, "filename") and resume.filename:
        try:
            upload_folder = os.path.join(BASE_DIR, "uploads")
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, resume.filename)
            with open(file_path, "wb") as buffer:
                buffer.write(await resume.read())
        except Exception as file_err:
            print(f"⚠️ File storage warning: {file_err}")

    # Create new applicant record for Aisha
    new_app = {
        "id": len(applications_db) + 1,
        "seeker": "Aisha",
        "email": "aisha@email.com",
        "job_title": "Backend Engineer",
        "company": "ABC Technologies",
        "skills": ["Python", "FastAPI", "SQL"],
        "status": "Applied",
        "applied_date": "10 July 2026",
        "cover_letter": cover_letter if cover_letter else "No cover letter provided.",
        "experience": "Entry Level Applicant",
        "notes": ""
    }
    
    applications_db.append(new_app)
    return RedirectResponse(url="/my-applications", status_code=303)


@app.get("/my-applications", response_class=HTMLResponse)
async def my_applications(request: Request):
    """Renders your specific applications list dynamically."""
    # Filter list to show Aisha's specific applications along with your seeded demo cards
    seeker_apps = [app for app in applications_db if app["seeker"] in ["Aisha", "Jane Lim", "David Wong"]]
    return templates.TemplateResponse(
        request=request, 
        name="my_application.html", 
        context={"applications": seeker_apps}
    )


# 💡 FIX 404 Route Catchers: Reroutes static layout file strings automatically to prevent errors
@app.get("/my_application.html")
@app.get("/my_applications.html")
async def explicit_my_application_redirect():
    return RedirectResponse(url="/my-applications", status_code=301)

@app.get("/notifications", response_class=HTMLResponse)
@app.get("/notifications.html")
async def get_notifications(request: Request):
    return templates.TemplateResponse(request=request, name="notifications.html")


# --- Employer Board Routes ---

@app.get("/employer/applications", response_class=HTMLResponse)
@app.get("/employer_applications.html", response_class=HTMLResponse)
async def employer_applications(request: Request):
    """Renders overview board tracking incoming applications."""
    return templates.TemplateResponse(
        request=request, 
        name="employer_applications.html", 
        context={"applicants": applications_db}
    )


@app.get("/employer/applicant/{applicant_id}", response_class=HTMLResponse)
async def applicant_detail(request: Request, applicant_id: int):
    """Renders candidate details view dynamically matching user ID parameters."""
    target_applicant = next((app for app in applications_db if app["id"] == applicant_id), None)
    if not target_applicant:
        raise HTTPException(status_code=404, detail="Applicant record not found.")
        
    return templates.TemplateResponse(
        request=request, 
        name="applicant_detail.html", 
        context={"applicant": target_applicant}
    )


@app.post("/employer/applicant/{applicant_id}/update")
async def update_applicant_stage(applicant_id: int, stage: str = Form(...), notes: Optional[str] = Form(None)):
    """Handles updating stage metrics dynamically across global application states."""
    for app_record in applications_db:
        if app_record["id"] == applicant_id:
            app_record["status"] = stage
            if notes is not None:
                app_record["notes"] = notes
            break
    return RedirectResponse(url="/employer/applications", status_code=303)