import os
from typing import Dict, List, Any
from fastapi import FastAPI, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
app = FastAPI(title="Agile CI Demo", version="0.1.0")

# --- Setup Paths for your UI folder structure ---
# Finds the root directory (job-portal/) relative to this file
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
UI_DIR = os.path.join(BASE_DIR, "UI")

# Mount your CSS folder so the browser can reach it via /UI/css
app.mount("/UI/css", StaticFiles(directory=os.path.join(UI_DIR, "css")), name="css")

# Point Jinja2 templates to your HTML directory
templates = Jinja2Templates(directory=os.path.join(UI_DIR, "html"))


# --- Your Existing To-Do Module Code ---
class Item(BaseModel):
    id: int
    title: str
    done: bool = False

_db: Dict[int, Item] = {}
applications_db = []
@app.get("/health")
def health() -> dict:
    """Simple health check endpoint used by tests and monitoring."""
    return {"status": "ok"}

@app.post("/items", status_code=201)
def create_item(item: Item) -> Item:
    if item.id in _db:
        raise HTTPException(status_code=409, detail="Item with that ID already exists")
    _db[item.id] = item
    return item


# --- Job Portal Module (Mock Database Setup) ---
# Seeds the mock DB with original data from your files
applications_db: List[Dict[str, Any]] = [
    {
        "id": 1,
        "seeker": "John Tan",
        "email": "john.tan@email.com",
        "job_title": "Backend Engineer",
        "skills": ["Python", "FastAPI", "SQL"],
        "status": "Screening",
        "applied_date": "10 July 2026",
    },
    {
        "id": 2,
        "seeker": "Jane Lim",
        "email": "jane.lim@email.com",
        "job_title": "Backend Engineer",
        "skills": ["React", "JavaScript"],
        "status": "Interview",
        "applied_date": "11 July 2026",
    },
    {
        "id": 3,
        "seeker": "David Wong",
        "email": "david.wong@email.com",
        "job_title": "Backend Engineer",
        "skills": ["Node.js", "MongoDB"],
        "status": "Applied",
        "applied_date": "12 July 2026",
    }
]


# --- Job Portal Routes ---

@app.get("/apply", response_class=HTMLResponse)
async def get_apply_page(request: Request):
    """Renders the apply job page view form."""
    # Use context= parameter explicitly to prevent Jinja2 dictionary hashing errors
    return templates.TemplateResponse(request=request, name="apply_job.html")


@app.post("/apply")
async def handle_application(
    request: Request,
    cover_letter: str = Form(None), 
    resume: Optional[UploadFile] = File(None) # Made fully optional with default None
):
    """Handles submission safely even if resume file or letter fields are blank."""
    
    # Safe guard file handling
    if resume and hasattr(resume, "filename") and resume.filename:
        try:
            upload_folder = os.path.join(BASE_DIR, "uploads")
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, resume.filename)
            with open(file_path, "wb") as buffer:
                buffer.write(await resume.read())
        except Exception as file_err:
            print(f"⚠️ File storage warning: {file_err}")

    # Build the dictionary row data packet safely
    new_app = {
        "id": len(applications_db) + 1,
        "seeker": "Aisha",
        "email": "aisha@email.com",
        "job_title": "Backend Engineer",
        "skills": ["Python", "FastAPI", "SQL"],
        "status": "Applied",
        "applied_date": "08 July 2026",
        "cover_letter": cover_letter if cover_letter else "No cover letter provided."
    }
    
    # Push into database row list
    applications_db.append(new_app)
    
    print("\n================ DATA SAVED ================")
    print(new_app)
    print("============================================\n")
    
    return RedirectResponse(url="/my-applications", status_code=303)


@app.get("/my-applications", response_class=HTMLResponse)
async def my_applications(request: Request):
    """Renders user's specific applications tracker interface."""
    return templates.TemplateResponse(request=request, name="my_application.html")


@app.get("/employer/applications", response_class=HTMLResponse)
async def employer_applications(request: Request):
    """Renders overview of candidates who applied for open positions."""
    return templates.TemplateResponse(
        request=request, 
        name="employer_applications.html", 
        context={"applicants": applications_db}
    )

def reset_db() -> None:
    _db.clear()