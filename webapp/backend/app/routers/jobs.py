from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Job, ParserProgress

router = APIRouter(prefix="/api", tags=["jobs"])


def _job_payload(db: Session, job: Job) -> dict:
    steps = db.query(ParserProgress).filter(ParserProgress.job_id == job.id).order_by(ParserProgress.id).all()
    return {
        "job_id": job.id,
        "case_id": job.case_id,
        "status": job.status,
        "total_steps": job.total_steps,
        "completed_steps": job.completed_steps,
        "error_message": job.error_message,
        "steps": [
            {
                "kind": s.kind,
                "name": s.name,
                "status": s.status,
                "num_events": s.num_events,
                "num_errors": s.num_errors,
                "num_warnings": s.num_warnings,
                "duration": s.duration,
            }
            for s in steps
        ],
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_payload(db, job)


@router.get("/cases/{case_id}/jobs/latest")
def get_latest_job(case_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.case_id == case_id).order_by(Job.created_at.desc()).first()
    if not job:
        raise HTTPException(404, "No jobs for this case")
    return _job_payload(db, job)
