from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.categories import CATEGORIES
from app.db import get_db
from app.models import Case, Job, ParserProgress
from app.services import data_service, upload_service

router = APIRouter(prefix="/api", tags=["cases"])


@router.get("/meta/parsers")
def list_parser_meta():
    return {"categories": CATEGORIES, "modules": data_service.module_meta()}


@router.get("/cases")
def list_cases(db: Session = Depends(get_db)):
    cases = db.query(Case).order_by(Case.created_at.desc()).all()
    return [
        {
            "id": c.id,
            "display_name": c.display_name,
            "status": c.status,
            "ios_version": c.ios_version,
            "model": c.model,
            "serial_number": c.serial_number,
            "created_at": c.created_at.isoformat(),
        }
        for c in cases
    ]


def _get_case(db: Session, case_id: str) -> Case:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return case


@router.get("/cases/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)):
    case = _get_case(db, case_id)
    latest_job = db.query(Job).filter(Job.case_id == case_id).order_by(Job.created_at.desc()).first()
    return {
        "id": case.id,
        "display_name": case.display_name,
        "status": case.status,
        "ios_version": case.ios_version,
        "model": case.model,
        "serial_number": case.serial_number,
        "created_at": case.created_at.isoformat(),
        "latest_job_id": latest_job.id if latest_job else None,
    }


@router.delete("/cases/{case_id}")
def delete_case(case_id: str, db: Session = Depends(get_db)):
    """Permanently remove a case: its extracted device data + parsed output on disk, any
    leftover upload staging, and every DB row (job history/progress cascade off the Case).

    A sysdiagnose archive is sensitive forensic data; letting cases pile up on the server
    is a standing risk, so an operator needs a way to wipe one once they're done with it.
    Delete is best-effort per resource and idempotent — a case that's already gone from
    disk still has its DB row removed, so a partial upload can always be cleaned up."""
    case = _get_case(db, case_id)

    # on-disk data (framework folder + cases.json entry)
    data_service.delete_case_data(case_id)

    # any upload staging that was never cleaned up (e.g. a case that failed before extraction)
    if case.source_upload_batch_id:
        upload_service.cleanup_batch(case.source_upload_batch_id)

    # DB rows: Case -> Jobs -> ParserProgress cascade via the relationships in models.py
    db.delete(case)
    db.commit()
    return {"deleted": case_id}


@router.get("/cases/{case_id}/overview")
def case_overview(case_id: str, db: Session = Depends(get_db)):
    """Category nav tree: for each parser/analyser, its static metadata plus this case's
    latest execution status/event count, so the frontend can render badges + gray out
    empty/unavailable sections without a second round trip."""
    case = _get_case(db, case_id)
    latest_job = db.query(Job).filter(Job.case_id == case_id).order_by(Job.created_at.desc()).first()

    progress_by_name = {}
    if latest_job:
        for step in db.query(ParserProgress).filter(ParserProgress.job_id == latest_job.id):
            progress_by_name[step.name] = step

    meta = data_service.module_meta()
    by_category: dict[str, list] = {c["id"]: [] for c in CATEGORIES}
    for name, m in sorted(meta.items()):
        step = progress_by_name.get(name)
        by_category[m["category"]].append(
            {
                "name": name,
                "kind": m["kind"],
                "description": m["description"],
                "format": m["format"],
                "is_timeline": m["is_timeline"],
                "status": step.status if step else "pending",
                "num_events": step.num_events if step else 0,
                "num_errors": step.num_errors if step else 0,
                "num_warnings": step.num_warnings if step else 0,
            }
        )

    unparsed = data_service.read_unparsed(case_id)

    return {
        "case": {"id": case.id, "display_name": case.display_name, "status": case.status},
        "categories": [
            {"id": c["id"], "label": c["label"], "modules": by_category[c["id"]]}
            for c in CATEGORIES
            if by_category[c["id"]]
        ],
        "unparsed_count": len(unparsed),
    }


@router.get("/cases/{case_id}/unparsed")
def case_unparsed(case_id: str, db: Session = Depends(get_db)):
    _get_case(db, case_id)
    return data_service.read_unparsed(case_id)


@router.get("/cases/{case_id}/parsers/{name}")
def case_parser_output(case_id: str, name: str, db: Session = Depends(get_db)):
    _get_case(db, case_id)
    meta, data = data_service.read_output(case_id, name)
    if meta is None:
        raise HTTPException(404, f"No parser or analyser named '{name}'")
    if data is None:
        raise HTTPException(404, "This module has not produced output for this case yet")
    return {"name": name, "meta": meta, "data": data}


@router.get("/cases/{case_id}/search")
def case_search(case_id: str, q: str, db: Session = Depends(get_db)):
    _get_case(db, case_id)
    if not q or len(q) < 2:
        raise HTTPException(400, "Query must be at least 2 characters")
    return {"query": q, "results": data_service.search_case(case_id, q)}
