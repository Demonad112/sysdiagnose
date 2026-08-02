"""``sdq status`` — one readiness report, built from everything on disk.

Reads what bootstrap, ingest, and the SAF parse/analyse runs already wrote:
capabilities, the ingest survey, per-module summaries, and the logarchive
index. Nothing here re-parses the case; it only reports state.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .env import REPO_ROOT, STATE_DIR


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _module_summaries(case_dir: Path) -> dict[str, dict]:
    logs_dir = case_dir / "logs"
    out: dict[str, dict] = {}
    if not logs_dir.is_dir():
        return out
    for f in logs_dir.glob("summary-*.json"):
        name = f.stem.removeprefix("summary-")
        data = _load_json(f)
        if data is not None:
            out[name] = data
    return out


def _logarchive_stats(case_dir: Path) -> dict | None:
    parquet = case_dir / "index" / "logarchive.parquet"
    if not parquet.is_file():
        return None
    stats = {"path": str(parquet), "bytes": parquet.stat().st_size}
    try:
        import pyarrow.parquet as pq

        meta = pq.ParquetFile(str(parquet)).metadata
        stats["rows"] = meta.num_rows
    except ImportError:
        pass
    return stats


def render(case_id: str, cases_path: Path) -> str:
    case_dir = cases_path / case_id
    lines: list[str] = []

    ingest = _load_json(STATE_DIR / f"ingest-{case_id}.json")
    if ingest:
        lines.append(f"case      {case_id}   ({'registered' if ingest.get('registered') else 'unregistered'})")
        lines.append(f"archive   {Path(ingest['archive']).name}  ({ingest['archive_bytes'] / 1e6:.1f} MB)")
        lines.append(f"data      {ingest['data_dir']}")
    else:
        lines.append(f"case      {case_id}   (no ingest record — run: sdq ingest <archive> --case-id {case_id})")

    caps = _load_json(STATE_DIR / "env.json")
    if caps:
        lines.append(f"store     {caps.get('store_tier', 'unknown')} tier")

    modules = _module_summaries(case_dir)
    if modules:
        has_events = [(n, s) for n, s in modules.items() if s.get("num_events", 0) > 0]
        ok = sorted(has_events, key=lambda t: -t[1]["num_events"])
        empty = [n for n, s in modules.items() if s.get("num_events", 0) == 0 and s.get("status") != "skipped"]
        skipped = [n for n, s in modules.items() if s.get("status") == "skipped"]
        errored = [n for n, s in modules.items() if s.get("num_errors", 0) > 0]

        lines.append("")
        lines.append(
            f"parsers   {len(ok)} produced events, {len(empty)} empty, {len(skipped)} skipped, {len(errored)} errored"
        )
        lines.append("")
        lines.append("modules with events (top 15)")
        for name, s in ok[:15]:
            lines.append(f"  {s['num_events']:>8,}  {name}")
        if errored:
            lines.append("")
            lines.append("modules with errors — see cases/<id>/logs/summary-<module>.json")
            for name in errored:
                lines.append(f"  !!  {name}")
    else:
        lines.append("")
        lines.append("no parser summaries yet — run: sysdiagnose -c <case> parse all -x logarchive,apps")

    la = _logarchive_stats(case_dir)
    if la:
        rows = la.get("rows")
        lines.append("")
        lines.append(f"logarchive index   {rows:,} events" if rows is not None else "logarchive index   present")
        lines.append(f"                   {la['bytes'] / 1e6:.1f} MB parquet, {la['path']}")
    else:
        lines.append("")
        lines.append("logarchive index   not built — run: python -m scripts.claude_analyst.logarchive_index <data_dir>")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    case_id = argv[0] if argv else "mac1"
    cases_path = Path(REPO_ROOT / "cases")
    print(render(case_id, cases_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
