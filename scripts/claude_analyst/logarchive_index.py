"""Stream a unified log decode straight into Parquet.

SAF's logarchive parser writes plain JSONL where `message` is duplicated inside
`data`, at roughly 1-2.5 KB/event — materialising a multi-million-event log that
way runs to tens of GB. This writes typed columns only and drops the redundant
nested payload, batching writes so memory stays bounded regardless of log size.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .env import find_unifiedlog_iterator

BATCH_SIZE = 250_000

# Columns kept from each decoded event. `message` alone carries the substance;
# `raw_message`, `message_entries` and `evidence` are dropped as redundant.
COLUMNS = [
    "timestamp",
    "subsystem",
    "category",
    "process",
    "pid",
    "thread_id",
    "activity_id",
    "event_type",
    "log_type",
    "message",
]


def _iter_events(logarchive_dir: Path):
    binary = find_unifiedlog_iterator()
    if not binary:
        raise SystemExit("no unifiedlog_iterator on PATH — run: scripts/sdq bootstrap")

    proc = subprocess.Popen(  # noqa: S603
        [binary, "--mode", "log-archive", "--input", str(logarchive_dir), "--format", "jsonl"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1 << 20,
    )
    errors = 0
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                errors += 1
    finally:
        proc.stdout.close()
        stderr = proc.stderr.read()
        proc.stderr.close()
        proc.wait()
    decode_errors = stderr.count("[ERROR]")
    if decode_errors:
        print(f"  (unifiedlog_iterator reported {decode_errors} decode errors on stderr)", file=sys.stderr)
    if errors:
        print(f"  ({errors} lines were not valid JSON and were skipped)", file=sys.stderr)


def build_index(case_dir: Path, *, quiet: bool = False) -> dict:
    """``case_dir`` is the extracted sysdiagnose folder, e.g.
    cases/<id>/data/sysdiagnose_.../ — the index is written to cases/<id>/index/,
    two levels up (out of data/), not beside the extracted folder.
    """
    logarchive_dir = case_dir / "system_logs.logarchive"
    if not logarchive_dir.is_dir():
        raise SystemExit(f"no system_logs.logarchive under {case_dir}")

    out_dir = case_dir.parent.parent / "index"
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / "logarchive.parquet"

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit("pyarrow not installed — run: scripts/sdq bootstrap") from None

    free = shutil.disk_usage(out_dir).free
    if free < 2e9:
        raise SystemExit(f"only {free / 1e9:.1f} GB free — need headroom for the index")

    schema = pa.schema(
        [
            ("timestamp", pa.string()),
            ("subsystem", pa.string()),
            ("category", pa.string()),
            ("process", pa.string()),
            ("pid", pa.string()),
            ("thread_id", pa.string()),
            ("activity_id", pa.string()),
            ("event_type", pa.string()),
            ("log_type", pa.string()),
            ("message", pa.string()),
        ]
    )

    t0 = time.time()
    writer = pq.ParquetWriter(str(parquet_path), schema, compression="zstd")
    batch: dict[str, list] = {c: [] for c in COLUMNS}
    total = 0

    try:
        for ev in _iter_events(logarchive_dir):
            for c in COLUMNS:
                v = ev.get(c)
                batch[c].append(str(v) if v is not None else None)
            total += 1
            if len(batch["timestamp"]) >= BATCH_SIZE:
                writer.write_table(pa.table(batch, schema=schema))
                batch = {c: [] for c in COLUMNS}
                if not quiet:
                    print(f"  ... {total:,} events indexed ({time.time() - t0:.0f}s)")
        if batch["timestamp"]:
            writer.write_table(pa.table(batch, schema=schema))
    finally:
        writer.close()

    elapsed = time.time() - t0
    size = parquet_path.stat().st_size
    return {
        "events": total,
        "seconds": elapsed,
        "parquet_path": str(parquet_path),
        "parquet_bytes": size,
    }


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m scripts.claude_analyst.logarchive_index <case_data_dir>", file=sys.stderr)
        return 2
    case_dir = Path(argv[0]).resolve()
    result = build_index(case_dir)
    print()
    print(f"events        {result['events']:,}")
    print(f"elapsed       {result['seconds']:.1f}s ({result['events'] / max(result['seconds'], 0.001):,.0f} ev/s)")
    print(f"parquet       {result['parquet_path']}  ({result['parquet_bytes'] / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
