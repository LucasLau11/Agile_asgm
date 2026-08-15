"""Employer's own company-profile management (US-05). Kept separate from
employer.py (job-posting management) — a distinct responsibility, mirroring
how auth.py is already its own file rather than folded into seeker.py."""

import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from job_portal.database import get_db
from job_portal.models import Employer
from job_portal.routes.auth import require_role
from job_portal.schemas import EmployerProfileOut, EmployerProfileUpdate
from job_portal.services.file_validation import MAX_RESUME_SIZE_BYTES, detect_safe_extension, sanitize_display_filename

router = APIRouter(prefix="/api/employers", tags=["employer-profile"])
# Kept outside /uploads because main.py publicly mounts that directory.
# Registration documents contain sensitive company information and must only
# be returned through the admin-authorized download endpoint.
VERIFICATION_UPLOAD_DIR = os.getenv("VERIFICATION_UPLOAD_DIR", "verification_documents")


@router.get("/me", response_model=EmployerProfileOut)
def get_employer_profile(
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
) -> EmployerProfileOut:
    employer = db.query(Employer).filter(Employer.id == employer_id).first()
    if employer is None:
        raise HTTPException(status_code=404, detail="Employer account not found.")
    return EmployerProfileOut.model_validate(employer)


@router.post("/me/verification-document", response_model=EmployerProfileOut, status_code=201)
async def submit_verification_document(
    registration_number: str = Form(...),
    file: UploadFile = File(...),
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
) -> EmployerProfileOut:
    """Submit an SSM registration document for administrator review."""
    registration_number = registration_number.strip()
    if not registration_number or len(registration_number) > 100:
        raise HTTPException(status_code=422, detail="A valid SSM registration number is required.")
    contents = await file.read()
    if len(contents) > MAX_RESUME_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Verification document must be under 5 MB.")
    extension = detect_safe_extension(contents)
    if extension is None:
        raise HTTPException(status_code=400, detail="Verification document must be a genuine PDF or DOCX file.")

    employer = db.query(Employer).filter(Employer.id == employer_id).first()
    if employer is None:
        raise HTTPException(status_code=404, detail="Employer account not found.")
    os.makedirs(VERIFICATION_UPLOAD_DIR, exist_ok=True)
    path = os.path.join(VERIFICATION_UPLOAD_DIR, f"{employer_id}_{uuid.uuid4().hex}{extension}")
    with open(path, "wb") as handle:
        handle.write(contents)
    if employer.verification_document_path and os.path.exists(employer.verification_document_path):
        os.remove(employer.verification_document_path)
    employer.registration_number = registration_number
    employer.verification_document_filename = sanitize_display_filename(file.filename)
    employer.verification_document_path = path
    employer.verification_submitted_at = datetime.utcnow()
    employer.verification_status = "pending"
    employer.verified_at = None
    employer.verified_by_admin_id = None
    employer.rejection_reason = None
    db.commit()
    db.refresh(employer)
    return EmployerProfileOut.model_validate(employer)


@router.put("/me", response_model=EmployerProfileOut)
def update_employer_profile(
    payload: EmployerProfileUpdate,
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
) -> EmployerProfileOut:
    employer = db.query(Employer).filter(Employer.id == employer_id).first()
    if employer is None:
        raise HTTPException(status_code=404, detail="Employer account not found.")
    employer.company_name = payload.company_name
    employer.description = payload.description
    employer.industry = payload.industry
    employer.website = payload.website
    db.commit()
    db.refresh(employer)
    return EmployerProfileOut.model_validate(employer)
