"""Chunked upload assembly.

Every write here streams directly to disk (open(...).write(chunk)) — at no point is an
entire file or archive held in memory. Chunks for an item live in their own directory
until all are present, then are concatenated in order into the final assembled file.
"""

import math
import os
import shutil
from pathlib import Path

from app.config import UPLOADS_ROOT


def batch_dir(batch_id: str) -> Path:
    return UPLOADS_ROOT / batch_id


def chunks_dir(batch_id: str, item_id: str) -> Path:
    return batch_dir(batch_id) / "chunks" / item_id


def assembled_root(batch_id: str) -> Path:
    return batch_dir(batch_id) / "assembled"


def assembled_item_path(batch_id: str, relative_path: str) -> Path:
    # relative_path comes from the client (folder upload); normalize to prevent path escape.
    safe_parts = [p for p in Path(relative_path).parts if p not in ("..", "", ".")]
    return assembled_root(batch_id).joinpath(*safe_parts)


def compute_total_chunks(size: int, chunk_size: int) -> int:
    if size == 0:
        return 1
    return math.ceil(size / chunk_size)


def write_chunk(batch_id: str, item_id: str, chunk_index: int, data: bytes) -> None:
    d = chunks_dir(batch_id, item_id)
    d.mkdir(parents=True, exist_ok=True)
    # write to temp then rename: makes re-sending the same chunk index idempotent/atomic
    tmp_path = d / f"{chunk_index}.part"
    final_path = d / f"{chunk_index}.chunk"
    with open(tmp_path, "wb") as f:
        f.write(data)
    os.replace(tmp_path, final_path)


def received_chunk_indexes(batch_id: str, item_id: str) -> list[int]:
    d = chunks_dir(batch_id, item_id)
    if not d.exists():
        return []
    return sorted(int(p.stem) for p in d.glob("*.chunk"))


def assemble_item(batch_id: str, item_id: str, relative_path: str, total_chunks: int) -> Path:
    """Concatenate all chunks for an item, in order, into the final file. Streams, never
    loads the whole file into memory."""
    dest = assembled_item_path(batch_id, relative_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    d = chunks_dir(batch_id, item_id)
    with open(dest, "wb") as out:
        for i in range(total_chunks):
            chunk_path = d / f"{i}.chunk"
            with open(chunk_path, "rb") as cf:
                shutil.copyfileobj(cf, out, length=1024 * 1024)
    # chunks no longer needed once assembled
    shutil.rmtree(d, ignore_errors=True)
    return dest


def cleanup_batch(batch_id: str) -> None:
    shutil.rmtree(batch_dir(batch_id), ignore_errors=True)
