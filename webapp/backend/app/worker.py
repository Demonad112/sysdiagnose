"""Background worker daemon: polls the jobs table and spawns one case_runner subprocess
per queued job. Deliberately simple (no Redis/Celery) — a single Postgres/SQLite table is
enough to queue jobs and to serve live per-parser progress to the frontend via polling,
and it's one fewer managed service to run on Railway.

Run as its own Railway service: `python -m app.worker`
"""

import subprocess
import sys
import time

from app.config import WORKER_POLL_INTERVAL
from app.db import SessionLocal, init_db
from app.models import Job


def claim_next_job(db) -> tuple[str, str] | None:
    # SQLite/Postgres both handle this fine at single-worker scale; if you ever run
    # multiple worker replicas, wrap this in `SELECT ... FOR UPDATE SKIP LOCKED` (Postgres).
    job = db.query(Job).filter(Job.status == "queued").order_by(Job.created_at).first()
    if job is None:
        return None
    job.status = "running"
    # read attributes out to plain values before commit expires them / session closes
    job_id, case_id = job.id, job.case_id
    db.commit()
    return job_id, case_id


def run_forever() -> None:
    init_db()
    print("sysdx worker started, polling for jobs...")
    while True:
        db = SessionLocal()
        try:
            claimed = claim_next_job(db)
        finally:
            db.close()

        if claimed is None:
            time.sleep(WORKER_POLL_INTERVAL)
            continue

        job_id, case_id = claimed
        print(f"Running job {job_id} (case {case_id})")
        # subprocess isolation: a native-code crash inside a parser only kills this job
        result = subprocess.run([sys.executable, "-m", "app.case_runner", "--job-id", job_id])

        if result.returncode != 0:
            # case_runner catches its own exceptions and marks the job failed; this branch
            # only fires on something catastrophic (e.g. SIGKILL/OOM) that skipped that logic.
            db = SessionLocal()
            try:
                job = db.get(Job, job_id)
                if job and job.status == "running":
                    job.status = "failed"
                    job.error_message = f"case_runner exited with code {result.returncode}"
                    db.commit()
            finally:
                db.close()


if __name__ == "__main__":
    run_forever()
