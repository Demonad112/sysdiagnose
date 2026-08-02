"""Idempotent environment setup.

Each step is skip-if-done and independently fallible: a single failure degrades
one capability rather than aborting the run. What actually happened is written to
``.sdq/env.json`` so ``sdq gaps`` can report blind spots later.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .env import IS_DARWIN, REPO_ROOT, STATE_DIR, TOOLS_DIR, VENV_DIR, YARA_DIR, find_unifiedlog_iterator, probe, save

UNIFIEDLOGS_REPO = "https://github.com/mandiant/macos-UnifiedLogs"
UNIFIEDLOGS_DIR = TOOLS_DIR / "macos-UnifiedLogs"

APT_PACKAGES = ["libmagic1", "graphviz", "yara", "sqlite3"]
EXTRA_PIP = ["duckdb", "pyarrow", "pytest", "packaging"]

# Direct-connect hosts. static.crates.io returns 403 through the agent proxy but
# 200 direct, so cargo cannot fetch crate tarballs unless it bypasses the proxy.
CARGO_DIRECT_HOSTS = "static.crates.io,crates.io,index.crates.io,github.com,codeload.github.com"


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str
    seconds: float
    skipped: bool = False


def _run(cmd: list[str], *, timeout: int = 1800, env: dict | None = None, cwd: Path | None = None):
    return subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env or dict(os.environ),
        cwd=str(cwd or REPO_ROOT),
    )


def _tail(text: str, n: int = 12) -> str:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return " | ".join(lines[-n:])[:800]


def venv_python() -> Path:
    return VENV_DIR / ("Scripts" if os.name == "nt" else "bin") / "python"


# --------------------------------------------------------------------------- steps


def step_apt() -> StepResult:
    t0 = time.time()
    if IS_DARWIN:
        return StepResult("apt packages", True, "skipped on macOS (use brew)", 0.0, skipped=True)
    if not shutil.which("apt-get"):
        return StepResult("apt packages", False, "apt-get not available", time.time() - t0)
    if os.geteuid() != 0 and not shutil.which("sudo"):
        return StepResult("apt packages", False, "not root and no sudo", time.time() - t0)

    prefix = [] if os.geteuid() == 0 else ["sudo"]
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    _run([*prefix, "apt-get", "update", "-qq"], timeout=600, env=env)
    res = _run([*prefix, "apt-get", "install", "-y", "-qq", *APT_PACKAGES], timeout=900, env=env)
    if res.returncode != 0:
        return StepResult("apt packages", False, _tail(res.stderr or res.stdout), time.time() - t0)
    return StepResult("apt packages", True, " ".join(APT_PACKAGES), time.time() - t0)


def step_venv() -> StepResult:
    t0 = time.time()
    py = venv_python()
    if py.exists():
        return StepResult("virtualenv", True, f"already at {VENV_DIR}", 0.0, skipped=True)
    res = _run([sys.executable, "-m", "venv", str(VENV_DIR)], timeout=600)
    if res.returncode != 0 or not py.exists():
        return StepResult("virtualenv", False, _tail(res.stderr), time.time() - t0)
    return StepResult("virtualenv", True, str(VENV_DIR), time.time() - t0)


def _pip_has(module: str) -> bool:
    py = venv_python()
    if not py.exists():
        return False
    res = _run([str(py), "-c", f"import {module}"], timeout=120)
    return res.returncode == 0


def step_pip_saf() -> StepResult:
    t0 = time.time()
    py = venv_python()
    if not py.exists():
        return StepResult("install SAF", False, "no venv", 0.0)
    if _pip_has("sysdiagnose"):
        return StepResult("install SAF", True, "already importable", 0.0, skipped=True)
    _run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], timeout=600)
    res = _run([str(py), "-m", "pip", "install", "-q", "-e", "."], timeout=2400)
    if res.returncode != 0:
        return StepResult("install SAF", False, _tail(res.stderr or res.stdout), time.time() - t0)
    ok = _pip_has("sysdiagnose")
    return StepResult("install SAF", ok, "editable install" if ok else "installed but import fails", time.time() - t0)


def step_pip_extras() -> StepResult:
    t0 = time.time()
    py = venv_python()
    if not py.exists():
        return StepResult("install query deps", False, "no venv", 0.0)
    missing = [p for p in EXTRA_PIP if not _pip_has(p)]
    if not missing:
        return StepResult("install query deps", True, "already present", 0.0, skipped=True)
    res = _run([str(py), "-m", "pip", "install", "-q", *missing], timeout=1800)
    still = [p for p in missing if not _pip_has(p)]
    if still:
        return StepResult(
            "install query deps", False, f"failed: {','.join(still)} :: {_tail(res.stderr)}", time.time() - t0
        )
    return StepResult("install query deps", True, " ".join(missing), time.time() - t0)


def step_yara_dir() -> StepResult:
    """YaraScanAnalyser raises FileNotFoundError when this is absent — not a soft skip."""
    t0 = time.time()
    existed = YARA_DIR.is_dir()
    YARA_DIR.mkdir(parents=True, exist_ok=True)
    n = len(list(YARA_DIR.glob("*.yar"))) + len(list(YARA_DIR.glob("*.yara")))
    detail = f"{YARA_DIR} ({n} rule file{'s' if n != 1 else ''})"
    return StepResult("yara dir", True, detail, time.time() - t0, skipped=existed)


def step_unifiedlog() -> StepResult:
    t0 = time.time()
    if IS_DARWIN:
        return StepResult("unifiedlog_iterator", True, "not needed — native /usr/bin/log", 0.0, skipped=True)
    existing = find_unifiedlog_iterator()
    if existing:
        return StepResult("unifiedlog_iterator", True, existing, 0.0, skipped=True)
    if not shutil.which("cargo"):
        return StepResult("unifiedlog_iterator", False, "cargo not installed", time.time() - t0)

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if not (UNIFIEDLOGS_DIR / ".git").exists():
        shutil.rmtree(UNIFIEDLOGS_DIR, ignore_errors=True)
        res = _run(["git", "clone", "--depth", "1", UNIFIEDLOGS_REPO, str(UNIFIEDLOGS_DIR)], timeout=900)
        if res.returncode != 0:
            return StepResult("unifiedlog_iterator", False, f"clone failed: {_tail(res.stderr)}", time.time() - t0)

    # The proxy 403s static.crates.io; cargo must reach it directly or the build
    # dies fetching crate tarballs. Augment rather than replace no_proxy.
    env = dict(os.environ)
    for key in ("no_proxy", "NO_PROXY"):
        current = env.get(key, "")
        env[key] = f"{current},{CARGO_DIRECT_HOSTS}" if current else CARGO_DIRECT_HOSTS
    env["CARGO_NET_GIT_FETCH_WITH_CLI"] = "true"

    build_dir = UNIFIEDLOGS_DIR / "examples" / "unifiedlog_iterator"
    if not build_dir.is_dir():
        return StepResult("unifiedlog_iterator", False, f"missing {build_dir}", time.time() - t0)

    res = _run(["cargo", "build", "--release"], timeout=3000, env=env, cwd=build_dir)
    found = find_unifiedlog_iterator()
    if not found:
        return StepResult("unifiedlog_iterator", False, f"build failed: {_tail(res.stderr)}", time.time() - t0)

    # Put it on PATH so SAF's logarchive parser, which invokes it by bare name, finds it.
    for dest_dir in ("/usr/local/bin", str(VENV_DIR / "bin")):
        try:
            dest = Path(dest_dir) / "unifiedlog_iterator"
            Path(dest_dir).mkdir(parents=True, exist_ok=True)
            shutil.copy2(found, dest)
            dest.chmod(0o755)
            found = str(dest)
            break
        except OSError:
            continue
    return StepResult("unifiedlog_iterator", True, found, time.time() - t0)


STEPS = [
    ("apt packages", step_apt),
    ("virtualenv", step_venv),
    ("install SAF", step_pip_saf),
    ("install query deps", step_pip_extras),
    ("yara dir", step_yara_dir),
    ("unifiedlog_iterator", step_unifiedlog),
]


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    skip_unifiedlog = "--skip-unifiedlog" in argv

    print(f"bootstrap: {REPO_ROOT}\n")
    results: list[StepResult] = []
    for name, fn in STEPS:
        if skip_unifiedlog and name == "unifiedlog_iterator":
            results.append(StepResult(name, True, "skipped by flag", 0.0, skipped=True))
            print(f"  ..   {name:<22} skipped by flag")
            continue
        print(f"  ->   {name} ...", flush=True)
        try:
            r = fn()
        except Exception as exc:  # a broken step must not take the rest down
            r = StepResult(name, False, f"{type(exc).__name__}: {exc}", 0.0)
        results.append(r)
        mark = "--" if r.skipped else ("ok" if r.ok else "!!")
        took = "" if r.skipped else f"  ({r.seconds:.1f}s)"
        print(f"  {mark}   {r.name:<22} {r.detail}{took}")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "bootstrap.json").write_text(json.dumps([r.__dict__ for r in results], indent=2) + "\n")

    caps = probe()
    save(caps)
    print()
    failed = [r for r in results if not r.ok]
    if failed:
        print(f"{len(failed)} step(s) failed: {', '.join(r.name for r in failed)}")
        print("This is survivable — see the warnings below for what it costs.\n")
    for w in caps.warnings():
        print(f"  warning: {w}")
    for b in caps.blockers():
        print(f"  BLOCKER: {b}")
    if not caps.blockers():
        print("\nbootstrap complete — ready to ingest.")
    return 1 if caps.blockers() else 0


if __name__ == "__main__":
    raise SystemExit(main())
