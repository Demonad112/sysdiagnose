"""Turn an archive into a registered, extracted case — and report what's in it.

Uses ``Sysdiagnose.create_case()`` where possible. When metadata extraction
refuses the archive (common for macOS captures, since SAF's detection is written
for iOS), falls back to a plain extract under an unregistered case id. That still
works: ``Sysdiagnose.parse()`` defaults to ``{"case_id": case_id}`` when the case
is not in the registry, and ``_ensure_case_metadata()`` re-derives from disk.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tarfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .env import REPO_ROOT, STATE_DIR

# Files whose presence (or absence) changes what questions can be answered.
SENTINELS = {
    "system_logs.logarchive": "unified log store",
    # Often benign: a single missing uuidtext file makes collection log an error
    # here while the tracev3 store itself is perfectly intact. Read it, don't
    # assume the capture failed.
    "oslog_archive_error.log": "unified log collection warnings",
    "sysdiagnose.log": "collection transcript",
    "remotectl_dumpstate.txt": "device identity",
    "ps.txt": "process snapshot",
    "taskinfo.txt": "task/memory detail",
    "sw_vers": "macOS version (macOS capture)",
    "SystemVersion.plist": "OS version (iOS capture)",
}


@dataclass
class IngestReport:
    case_id: str
    archive: str
    archive_bytes: int
    case_dir: str
    data_dir: str
    registered: bool
    extract_seconds: float
    file_count: int
    total_bytes: int
    top_extensions: list = field(default_factory=list)
    largest_files: list = field(default_factory=list)
    sentinels: dict = field(default_factory=dict)
    logarchive_tracev3: int = 0
    notes: list = field(default_factory=list)

    def render(self) -> str:
        out = [
            f"case      {self.case_id}   ({'registered' if self.registered else 'UNREGISTERED — metadata fallback'})",
            f"archive   {Path(self.archive).name}  ({self.archive_bytes / 1e6:.1f} MB)",
            f"data      {self.data_dir}",
            f"extracted {self.file_count:,} files, {self.total_bytes / 1e6:.1f} MB, in {self.extract_seconds:.1f}s",
            "",
            "key artifacts",
        ]
        for name, why in SENTINELS.items():
            present = self.sentinels.get(name, False)
            mark = "ok  " if present else "--  "
            if name == "oslog_archive_error.log" and present:
                mark = "!!  "
            out.append(f"  {mark}{name:<28} {why}")

        if self.sentinels.get("system_logs.logarchive"):
            out.append(f"\n  logarchive contains {self.logarchive_tracev3} tracev3 file(s)")

        out.append("\nfile types by count")
        for ext, n, size in self.top_extensions[:14]:
            out.append(f"  {n:>7,}  {size / 1e6:>8.1f} MB  {ext}")

        out.append("\nlargest files")
        for path, size in self.largest_files[:10]:
            out.append(f"  {size / 1e6:>8.1f} MB  {path}")

        if self.notes:
            out.append("\nnotes")
            out.extend(f"  - {n}" for n in self.notes)
        return "\n".join(out)


def _survey(root: Path) -> tuple[int, int, list, list, dict, int]:
    ext_count: Counter = Counter()
    ext_size: Counter = Counter()
    largest: list[tuple[str, int]] = []
    sentinels = dict.fromkeys(SENTINELS, False)
    tracev3 = 0
    total = 0
    n = 0

    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        for name in dirnames:
            if name in sentinels:
                sentinels[name] = True
        for name in filenames:
            p = d / name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            n += 1
            total += size
            ext = p.suffix.lower() or "(no extension)"
            ext_count[ext] += 1
            ext_size[ext] += size
            largest.append((str(p.relative_to(root)), size))
            if name in sentinels:
                sentinels[name] = True
            if name.endswith(".tracev3"):
                tracev3 += 1

    largest.sort(key=lambda t: -t[1])
    top = [(e, c, ext_size[e]) for e, c in ext_count.most_common(30)]
    return n, total, top, largest[:25], sentinels, tracev3


def _unsafe_extract(archive: Path, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tf:
        try:
            tf.extractall(path=data_dir, filter="data")
        except TypeError:  # python < 3.12 has no filter kwarg
            tf.extractall(path=data_dir)  # noqa: S202


def ingest(archive: Path, case_id: str | None, cases_path: Path, force: bool) -> IngestReport:
    archive = archive.resolve()
    if not archive.is_file():
        raise SystemExit(f"no such archive: {archive}")

    size = archive.stat().st_size
    free = shutil.disk_usage(cases_path.parent if cases_path.exists() else REPO_ROOT).free
    if free < size * 6:
        raise SystemExit(f"not enough disk: {free / 1e9:.1f} GB free for a {size / 1e6:.0f} MB archive")

    os.environ["SYSDIAGNOSE_CASES_PATH"] = str(cases_path)
    from sysdiagnose import Sysdiagnose  # imported late: needs the venv

    sd = Sysdiagnose(str(cases_path))
    notes: list[str] = []
    registered = True
    t0 = time.time()

    try:
        case = sd.create_case(str(archive), force, case_id) if case_id else sd.create_case(str(archive), force)
        resolved = str(case["case_id"]) if isinstance(case, dict) else str(case_id)
    except Exception as exc:
        # SAF's metadata detection is iOS-shaped; a macOS capture can legitimately
        # fail it. Extract anyway — parsers accept an unregistered case id.
        notes.append(f"create_case refused the archive ({type(exc).__name__}: {exc}); used plain extract instead")
        registered = False
        resolved = case_id or "1"
        _unsafe_extract(archive, cases_path / resolved / "data")

    elapsed = time.time() - t0
    data_dir = cases_path / resolved / "data"
    if not data_dir.is_dir():
        raise SystemExit(f"expected extracted data at {data_dir}, but it does not exist")

    n, total, top, largest, sentinels, tracev3 = _survey(data_dir)

    if sentinels.get("oslog_archive_error.log"):
        # Quote it rather than calling the capture failed. Usually it is a handful
        # of missing uuidtext symbol files, which costs symbolication on a few
        # messages and nothing else.
        errs = list(root_dir.rglob("oslog_archive_error.log")) if (root_dir := data_dir) else []
        detail = ""
        if errs:
            try:
                lines = [ln.strip() for ln in errs[0].read_text(errors="replace").splitlines() if ln.strip()]
                detail = f" ({len(lines)} line(s); first: {lines[0][:120]})" if lines else " (empty)"
            except OSError:
                pass
        notes.append(
            f"oslog_archive_error.log present{detail} — check it before concluding the log capture failed; "
            "missing uuidtext entries only cost symbolication"
        )
    if not sentinels.get("system_logs.logarchive"):
        notes.append("no system_logs.logarchive — unified log events will be absent from the timeline")
    elif tracev3 == 0:
        notes.append("system_logs.logarchive exists but contains no tracev3 files — nothing to decode")
    if sentinels.get("sw_vers") and not sentinels.get("SystemVersion.plist"):
        notes.append("macOS capture — expect many iOS-targeted SAF parsers to return nothing")

    return IngestReport(
        case_id=resolved,
        archive=str(archive),
        archive_bytes=size,
        case_dir=str(cases_path / resolved),
        data_dir=str(data_dir),
        registered=registered,
        extract_seconds=elapsed,
        file_count=n,
        total_bytes=total,
        top_extensions=top,
        largest_files=largest,
        sentinels=sentinels,
        logarchive_tracev3=tracev3,
        notes=notes,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sdq ingest")
    ap.add_argument("archive", help="path to a sysdiagnose .tar.gz")
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--cases-path", default=os.getenv("SYSDIAGNOSE_CASES_PATH", str(REPO_ROOT / "cases")))
    ap.add_argument("--force", action="store_true", help="re-create the case if it already exists")
    args = ap.parse_args(argv)

    cases_path = Path(args.cases_path).resolve()
    cases_path.mkdir(parents=True, exist_ok=True)

    report = ingest(Path(args.archive), args.case_id, cases_path, args.force)
    print(report.render())

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"ingest-{report.case_id}.json").write_text(json.dumps(asdict(report), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
