"""Runs entirely inside its own subprocess (spawned by the worker), one per job.

Why a subprocess instead of running this in-process in the worker daemon: several parsers
shell out to native tools (yara, sqlite, the unifiedlog_iterator rust binary) or parse
untrusted binary plists — a hard crash there should only take down this one job, not the
long-lived worker daemon. Everything below still talks to the sysdiagnose framework via
direct Python import (not CLI text-scraping); the subprocess boundary is purely for
fault isolation.
"""

import argparse
import importlib
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# make sure app.config runs first: it sets SYSDIAGNOSE_CASES_PATH before the framework reads it
from app import config  # noqa: F401
from app.db import SessionLocal
from app.models import Case, Job, ParserProgress


def _import_instance(kind: str, name: str, sd_config, case: dict):
    from sysdiagnose.utils.base import BaseAnalyserInterface, BaseParserInterface

    base_class = BaseParserInterface if kind == "parser" else BaseAnalyserInterface
    module = importlib.import_module(f"sysdiagnose.{kind}s.{name}")
    for attr in dir(module):
        obj = getattr(module, attr)
        if isinstance(obj, type) and issubclass(obj, base_class) and obj is not base_class:
            return obj(config=sd_config, case=case)
    raise NotImplementedError(f"{kind} '{name}' does not exist or has problems")


def run_job(job_id: str) -> None:
    db = SessionLocal()
    job = db.get(Job, job_id)
    if job is None:
        print(f"Job {job_id} not found", file=sys.stderr)
        return
    case_row = db.get(Case, job.case_id)

    job.status = "running"
    job.started_at = datetime.utcnow()
    case_row.status = "processing"
    db.commit()

    try:
        from sysdiagnose import Sysdiagnose

        sd = Sysdiagnose()
        parsers = sd.config.get_parsers()  # name -> description
        analysers = sd.config.get_analysers()
        job.total_steps = len(parsers) + len(analysers) + 1  # +1 for extraction/create_case
        db.commit()

        # --- step 0: extract archive / copy folder + register case -------------------------
        step = ParserProgress(job_id=job.id, kind="setup", name="extract", status="running")
        db.add(step)
        db.commit()
        t0 = time.time()
        try:
            case_meta = sd.create_case(job.case.source_path, force=True, case_id=job.case_id)
            step.status, step.duration = "success", time.time() - t0
            case_row.ios_version = case_meta.get("ios_version")
            case_row.model = case_meta.get("model")
            case_row.serial_number = case_meta.get("serial_number")
        except Exception as e:
            step.status, step.duration = "error", time.time() - t0
            job.status, job.error_message, case_row.status = "failed", str(e), "error"
            db.commit()
            return
        job.completed_steps += 1
        db.commit()

        referenced_files: set[str] = set()
        case_dict = sd.cases()[job.case_id]

        # --- run parsers, one by one, tracking which raw files each one consumed ------------
        for name in sorted(parsers):
            _run_step(db, job, sd.config, case_dict, "parser", name, referenced_files)

        # --- run analysers (they build on parsed_data, so run after all parsers) ------------
        for name in sorted(analysers):
            _run_step(db, job, sd.config, case_dict, "analyser", name, referenced_files)

        _write_unparsed_bucket(sd.config, job.case_id, referenced_files)

        job.status = "completed"
        job.finished_at = datetime.utcnow()
        case_row.status = "ready"
        db.commit()
    except Exception as e:
        job.status = "failed"
        job.error_message = f"{e}\n{traceback.format_exc()}"
        case_row.status = "error"
        db.commit()
    finally:
        db.close()


def _run_step(db, job, sd_config, case_dict, kind: str, name: str, referenced_files: set[str]) -> None:
    step = ParserProgress(job_id=job.id, kind=kind, name=name, status="running", started_at=datetime.utcnow())
    db.add(step)
    db.commit()
    try:
        instance = _import_instance(kind, name, sd_config, case_dict)
        if kind == "parser":
            try:
                for f in instance.get_log_files():
                    referenced_files.add(os.path.abspath(f))
            except Exception:
                pass  # best-effort: some parsers compute this lazily/oddly, unparsed bucket just misses a few
        instance.save_result(force=True)
        summary = instance.get_result_summary()
        step.status = str(summary.status)  # StrEnum: "ok" | "warning" | "error" | "skipped"
        step.num_events = summary.num_events
        step.num_errors = summary.num_errors
        step.num_warnings = summary.num_warnings
        step.duration = summary.duration
    except NotImplementedError:
        step.status = "skipped"
    except Exception as e:
        step.status = "error"
        step.num_errors = 1
        print(f"{kind} '{name}' crashed: {e}", file=sys.stderr)
        traceback.print_exc()
    finally:
        step.finished_at = datetime.utcnow()
        job.completed_steps += 1
        db.commit()


def _write_unparsed_bucket(sd_config, case_id: str, referenced_files: set[str]) -> None:
    """Diff every file under the case's extracted data folder against the files every
    parser reported consuming via get_log_files(). Anything left over has no parser and
    is bucketed as unparsed/raw so it's still visible instead of silently dropped."""
    case_data_folder = sd_config.get_case_data_folder(case_id)
    unparsed = []
    for root, _dirs, files in os.walk(case_data_folder):
        for fname in files:
            full = os.path.abspath(os.path.join(root, fname))
            if full in referenced_files:
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                size = None
            unparsed.append({"path": os.path.relpath(full, case_data_folder), "size": size})

    unparsed.sort(key=lambda x: x["path"])
    out_path = Path(sd_config.get_case_parsed_data_folder(case_id)) / "_unparsed.json"
    with open(out_path, "w") as f:
        json.dump(unparsed, f, indent=2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", required=True)
    args = ap.parse_args()
    run_job(args.job_id)


if __name__ == "__main__":
    main()
