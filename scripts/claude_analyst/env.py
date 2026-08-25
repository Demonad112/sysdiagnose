"""Capability probe. Stdlib only — this must run before the venv exists.

``sdq doctor`` renders the result. Everything else reads :func:`probe` to decide
what it is allowed to attempt.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_DIR = REPO_ROOT / ".venv"
TOOLS_DIR = REPO_ROOT / "tools"
STATE_DIR = REPO_ROOT / ".sdq"
YARA_DIR = REPO_ROOT / "yara"
ENV_FILE = STATE_DIR / "env.json"

IS_DARWIN = platform.system() == "Darwin"

# Python packages the analysis layer needs, and what breaks without each.
PY_REQUIREMENTS = {
    "sysdiagnose": "SAF itself — nothing works without it",
    "duckdb": "SQL query tier (falls back to pyarrow, then sqlite3)",
    "pyarrow": "Parquet writing (falls back to JSONL)",
    "magic": "file type detection in the residual sweep",
    "nska_deserialize": "NSKeyedArchiver plists stay opaque without it",
    "pandas": "used by several SAF analysers",
}

# External binaries. `required` means the pipeline is meaningfully degraded.
BINARIES = {
    "git": "clone the unified-log extractor",
    "cargo": "build the unified-log extractor",
    "tar": "archive extraction",
    "file": "magic-based type detection",
    "rg": "fast text search across the case",
    "curl": "fetch archives over HTTPS",
    "dot": "ps_matrix analyser only",
    "sqlite3": "convenience only — Python's sqlite3 module is what we actually use",
}


def _venv_python() -> Path | None:
    exe = VENV_DIR / ("Scripts" if os.name == "nt" else "bin") / "python"
    return exe if exe.exists() else None


def _unifiedlog_candidates() -> list[Path]:
    """The binary lands in one of two places depending on cargo's workspace layout."""
    base = TOOLS_DIR / "macos-UnifiedLogs"
    return [
        base / "target" / "release" / "unifiedlog_iterator",
        base / "examples" / "target" / "release" / "unifiedlog_iterator",
        Path("/usr/local/bin/unifiedlog_iterator"),
    ]


def find_unifiedlog_iterator() -> str | None:
    for cand in _unifiedlog_candidates():
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    found = shutil.which("unifiedlog_iterator")
    return found


@dataclass
class Capabilities:
    platform: str
    python: str
    venv: str | None
    packages: dict[str, bool] = field(default_factory=dict)
    binaries: dict[str, str | None] = field(default_factory=dict)
    unifiedlog: str | None = None
    apple_log: str | None = None
    disk_free_gb: float = 0.0
    disk_total_gb: float = 0.0
    yara_rules: int = 0
    store_tier: str = "none"
    can_decode_logarchive: bool = False

    def blockers(self) -> list[str]:
        out = []
        if not self.venv:
            out.append("no virtualenv — run: scripts/sdq bootstrap")
        elif not self.packages.get("sysdiagnose"):
            out.append("SAF not installed in the venv — run: scripts/sdq bootstrap")
        if self.disk_free_gb < 8:
            out.append(f"only {self.disk_free_gb:.1f} GB free; a 400 MB archive needs ~10 GB")
        return out

    def warnings(self) -> list[str]:
        out = []
        if not self.can_decode_logarchive:
            out.append(
                "unified logs cannot be decoded (no unifiedlog_iterator, no /usr/bin/log). "
                "Everything else still works; the timeline will be missing os_log events."
            )
        if self.store_tier == "sqlite":
            out.append("duckdb and pyarrow both missing — `sdq sql` will be unavailable")
        elif self.store_tier == "pyarrow":
            out.append("duckdb missing — Parquet works but `sdq sql` will be unavailable")
        if not self.packages.get("magic"):
            out.append("python-magic missing — residual sweep falls back to extension sniffing")
        if not self.packages.get("nska_deserialize"):
            out.append("nska-deserialize missing — NSKeyedArchiver plists will not resolve")
        if self.yara_rules == 0:
            out.append("no YARA rules in yara/ — yarascan will be skipped")
        return out


def _probe_packages(py: Path | None) -> dict[str, bool]:
    """Import-check inside the venv if it exists, otherwise the current interpreter."""
    names = list(PY_REQUIREMENTS)
    # Actually import rather than find_spec: `sysdiagnose` resolves from src/ via
    # PYTHONPATH even when none of its dependencies are installed, so a spec check
    # would report it usable when importing it actually raises.
    code = (
        "import json\n"
        f"names = {names!r}\n"
        "res = {}\n"
        "for n in names:\n"
        "    try:\n"
        "        __import__(n)\n"
        "        res[n] = True\n"
        "    except Exception:\n"
        "        res[n] = False\n"
        "print(json.dumps(res))\n"
    )
    exe = str(py) if py else sys.executable
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    try:
        res = subprocess.run(  # noqa: S603
            [exe, "-c", code], capture_output=True, text=True, timeout=90, env=env, cwd=str(REPO_ROOT)
        )
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout.strip().splitlines()[-1])
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        pass
    return dict.fromkeys(names, False)


def probe() -> Capabilities:
    py = _venv_python()
    packages = _probe_packages(py)
    binaries = {name: shutil.which(name) for name in BINARIES}

    unifiedlog = find_unifiedlog_iterator()
    apple_log = "/usr/bin/log" if IS_DARWIN and Path("/usr/bin/log").exists() else None

    usage = shutil.disk_usage(REPO_ROOT)
    yara_rules = len(list(YARA_DIR.glob("*.yar"))) + len(list(YARA_DIR.glob("*.yara"))) if YARA_DIR.is_dir() else 0

    if packages.get("duckdb"):
        tier = "duckdb"
    elif packages.get("pyarrow"):
        tier = "pyarrow"
    else:
        tier = "sqlite"

    return Capabilities(
        platform=f"{platform.system()} {platform.machine()}",
        python=platform.python_version(),
        venv=str(py) if py else None,
        packages=packages,
        binaries=binaries,
        unifiedlog=unifiedlog,
        apple_log=apple_log,
        disk_free_gb=usage.free / 1e9,
        disk_total_gb=usage.total / 1e9,
        yara_rules=yara_rules,
        store_tier=tier,
        can_decode_logarchive=bool(unifiedlog or apple_log),
    )


def save(caps: Capabilities) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(json.dumps(asdict(caps), indent=2) + "\n")
    return ENV_FILE


def _mark(ok: bool) -> str:
    return "ok  " if ok else "MISS"


def render(caps: Capabilities) -> str:
    lines: list[str] = []
    lines.append(f"platform   {caps.platform}   python {caps.python}")
    lines.append(f"venv       {caps.venv or '(none)'}")
    lines.append(f"disk       {caps.disk_free_gb:.1f} GB free of {caps.disk_total_gb:.1f} GB")
    lines.append(f"store tier {caps.store_tier}")
    lines.append("")

    lines.append("python packages")
    for name, why in PY_REQUIREMENTS.items():
        lines.append(f"  {_mark(caps.packages.get(name, False))}  {name:<18} {why}")
    lines.append("")

    lines.append("binaries")
    for name, why in BINARIES.items():
        path = caps.binaries.get(name)
        lines.append(f"  {_mark(bool(path))}  {name:<18} {path or why}")
    lines.append("")

    lines.append("unified logs")
    if caps.apple_log:
        lines.append(f"  ok    native Apple log at {caps.apple_log}")
    elif caps.unifiedlog:
        lines.append(f"  ok    unifiedlog_iterator at {caps.unifiedlog}")
    else:
        lines.append("  MISS  no decoder — build with: scripts/sdq bootstrap")
    lines.append("")

    blockers = caps.blockers()
    warnings = caps.warnings()
    if blockers:
        lines.append("BLOCKERS")
        lines.extend(f"  - {b}" for b in blockers)
        lines.append("")
    if warnings:
        lines.append("warnings")
        lines.extend(f"  - {w}" for w in warnings)
        lines.append("")
    if not blockers:
        lines.append("ready to ingest.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    caps = probe()
    if "--json" in argv:
        print(json.dumps(asdict(caps), indent=2))
    else:
        print(render(caps))
    save(caps)
    return 1 if caps.blockers() else 0


if __name__ == "__main__":
    raise SystemExit(main())
