"""Employer's own company-profile management (US-05). Kept separate from
employer.py (job-posting management) — a distinct responsibility, mirroring
how auth.py is already its own file rather than folded into seeker.py."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from job_portal.database import get_db
from job_portal.models import Employer
from job_portal.routes.auth import require_role
from job_portal.schemas import EmployerProfileOut, EmployerProfileUpdate

router = APIRouter(prefix="/api/employers", tags=["employer-profile"])


@router.get("/me", response_model=EmployerProfileOut)
def get_employer_profile(
    employer_id: int = Depends(require_role("employer", "Must be logged in as an employer.")),
    db: Session = Depends(get_db),
) -> EmployerProfileOut:
    employer = db.query(Employer).filter(Employer.id == employer_id).first()
    if employer is None:
        raise HTTPException(status_code=404, detail="Employer account not found.")
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
