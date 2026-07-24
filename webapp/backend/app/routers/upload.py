import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import CHUNK_SIZE_BYTES
from app.db import get_db
from app.models import Case, Job, UploadBatch, UploadItem
from app.schemas import (
    CompleteBatchResponse,
    CompleteItemResponse,
    CreateBatchRequest,
    CreateBatchResponse,
    ItemStatusResponse,
    RegisterItemRequest,
    RegisterItemResponse,
)
from app.services import upload_service

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


def _get_batch(db: Session, batch_id: str) -> UploadBatch:
    batch = db.get(UploadBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Upload batch not found")
    return batch


def _get_item(db: Session, batch_id: str, item_id: str) -> UploadItem:
    item = db.get(UploadItem, item_id)
    if not item or item.batch_id != batch_id:
        raise HTTPException(404, "Upload item not found")
    return item


@router.post("", response_model=CreateBatchResponse)
def create_batch(payload: CreateBatchRequest, db: Session = Depends(get_db)):
    if payload.mode not in ("archive", "folder"):
        raise HTTPException(400, "mode must be 'archive' or 'folder'")
    batch = UploadBatch(mode=payload.mode)
    db.add(batch)
    db.commit()
    return CreateBatchResponse(batch_id=batch.id, chunk_size=CHUNK_SIZE_BYTES)


@router.post("/{batch_id}/items", response_model=RegisterItemResponse)
def register_item(batch_id: str, payload: RegisterItemRequest, db: Session = Depends(get_db)):
    batch = _get_batch(db, batch_id)
    if batch.status != "uploading":
        raise HTTPException(409, f"Batch is not accepting uploads (status={batch.status})")

    total_chunks = upload_service.compute_total_chunks(payload.size, CHUNK_SIZE_BYTES)
    item = UploadItem(
        id=uuid.uuid4().hex,
        batch_id=batch_id,
        relative_path=payload.relative_path,
        size=payload.size,
        chunk_size=CHUNK_SIZE_BYTES,
        total_chunks=total_chunks,
        received_chunks=[],
        status="uploading",
    )
    db.add(item)
    db.commit()
    return RegisterItemResponse(
        item_id=item.id, total_chunks=total_chunks, chunk_size=CHUNK_SIZE_BYTES, received_chunks=[]
    )


@router.get("/{batch_id}/items/{item_id}/status", response_model=ItemStatusResponse)
def item_status(batch_id: str, item_id: str, db: Session = Depends(get_db)):
    item = _get_item(db, batch_id, item_id)
    received = upload_service.received_chunk_indexes(batch_id, item_id) if item.status == "uploading" else []
    return ItemStatusResponse(
        item_id=item.id, status=item.status, total_chunks=item.total_chunks, received_chunks=received
    )


@router.put("/{batch_id}/items/{item_id}/chunks/{chunk_index}")
async def upload_chunk(batch_id: str, item_id: str, chunk_index: int, request: Request, db: Session = Depends(get_db)):
    item = _get_item(db, batch_id, item_id)
    if item.status != "uploading":
        raise HTTPException(409, f"Item is not accepting chunks (status={item.status})")
    if not (0 <= chunk_index < item.total_chunks):
        raise HTTPException(400, "chunk_index out of range")

    # stream the request body straight to disk, never buffer the whole chunk in a Python list
    data = await request.body()
    upload_service.write_chunk(batch_id, item_id, chunk_index, data)
    return {"received": chunk_index}


@router.post("/{batch_id}/items/{item_id}/complete", response_model=CompleteItemResponse)
def complete_item(batch_id: str, item_id: str, db: Session = Depends(get_db)):
    item = _get_item(db, batch_id, item_id)
    received = set(upload_service.received_chunk_indexes(batch_id, item_id))
    missing = [i for i in range(item.total_chunks) if i not in received]
    if missing:
        raise HTTPException(409, f"Missing chunks: {missing[:10]}{'...' if len(missing) > 10 else ''}")

    upload_service.assemble_item(batch_id, item_id, item.relative_path, item.total_chunks)
    item.status = "assembled"
    db.commit()
    return CompleteItemResponse(item_id=item.id, status=item.status)


@router.post("/{batch_id}/complete", response_model=CompleteBatchResponse)
def complete_batch(batch_id: str, db: Session = Depends(get_db)):
    batch = _get_batch(db, batch_id)
    items = db.query(UploadItem).filter(UploadItem.batch_id == batch_id).all()
    if not items:
        raise HTTPException(400, "Batch has no items")
    not_assembled = [i.relative_path for i in items if i.status != "assembled"]
    if not_assembled:
        raise HTTPException(409, f"Items not yet assembled: {not_assembled[:5]}")

    if batch.mode == "archive":
        if len(items) != 1:
            raise HTTPException(400, "archive mode expects exactly one file")
        source_path = str(upload_service.assembled_item_path(batch_id, items[0].relative_path))
    else:
        source_path = upload_service.resolve_folder_source(batch_id)

    case_id = f"sysdx_{uuid.uuid4().hex[:12]}"
    display_name = items[0].relative_path.split("/")[0] if batch.mode == "folder" else items[0].relative_path

    case = Case(
        id=case_id,
        display_name=display_name,
        source_upload_batch_id=batch_id,
        source_path=source_path,
        status="pending",
    )
    job = Job(case_id=case_id, status="queued")
    batch.status = "ready"
    batch.case_id = case_id

    db.add(case)
    db.add(job)
    db.commit()

    return CompleteBatchResponse(batch_id=batch_id, case_id=case_id, job_id=job.id)
