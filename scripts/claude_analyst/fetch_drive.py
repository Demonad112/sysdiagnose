"""Fetch a sysdiagnose archive over HTTPS, resumably.

Google Drive's MCP tools return base64 through the conversation, which is
unusable at archive scale. A link-shared Drive file is fetchable anonymously
over plain HTTPS instead, so that is what this does.

Guards worth having: Drive answers a large-file request with an HTML virus-scan
interstitial rather than an error, and writing that to disk produces a "corrupt
archive" that is really a web page.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .env import REPO_ROOT

DRIVE_DIRECT = "https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t"
DEFAULT_DEST = REPO_ROOT / "archives"

# Extracted size is typically 6-10x compressed for a sysdiagnose; the pipeline
# then wants roughly as much again for parsed output and the index.
DISK_MULTIPLIER = 12


@dataclass
class Fetched:
    path: Path
    size: int
    sha256: str
    declared_uncompressed: int | None

    def summary(self) -> str:
        lines = [
            f"archive   {self.path}",
            f"size      {self.size:,} bytes ({self.size / 1e6:.1f} MB)",
            f"sha256    {self.sha256}",
        ]
        if self.declared_uncompressed:
            lines.append(
                f"extracts  ~{self.declared_uncompressed / 1e9:.2f} GB (gzip ISIZE; modulo 4 GiB, so a lower bound)"
            )
        return "\n".join(lines)


def drive_id(ref: str) -> str:
    """Accept a bare id, a /file/d/<id>/view URL, or a ?id=<id> URL."""
    for pattern in (r"/file/d/([A-Za-z0-9_-]{10,})", r"[?&]id=([A-Za-z0-9_-]{10,})"):
        m = re.search(pattern, ref)
        if m:
            return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", ref):
        return ref
    raise ValueError(f"could not find a Drive file id in {ref!r}")


def _looks_like_html(path: Path) -> bool:
    with path.open("rb") as fh:
        head = fh.read(512).lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<title>" in head[:200]


def _gzip_isize(path: Path) -> int | None:
    """Last 4 bytes of a gzip member are the uncompressed size mod 2**32."""
    try:
        size = path.stat().st_size
        if size < 8:
            return None
        with path.open("rb") as fh:
            if fh.read(2) != b"\x1f\x8b":
                return None
            fh.seek(-4, 2)
            return struct.unpack("<I", fh.read(4))[0]
    except OSError:
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def preflight(dest_dir: Path, expected_size: int | None) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(dest_dir).free
    if expected_size:
        need = expected_size * DISK_MULTIPLIER
        if free < need:
            raise SystemExit(
                f"not enough disk: {free / 1e9:.1f} GB free, need ~{need / 1e9:.1f} GB "
                f"for a {expected_size / 1e6:.0f} MB archive (extract + parse + index)"
            )
    elif free < 10e9:
        raise SystemExit(f"not enough disk: {free / 1e9:.1f} GB free, want at least 10 GB")


def fetch(ref: str, dest: Path, *, expected_size: int | None = None, quiet: bool = False) -> Fetched:
    file_id = drive_id(ref)
    url = DRIVE_DIRECT.format(id=file_id)
    preflight(dest.parent, expected_size)

    cmd = [
        "curl", "-L",
        "-C", "-",            # resume a partial file rather than restarting
        "--retry", "5",
        "--retry-delay", "2",
        "--retry-connrefused",
        "--fail",
        "-o", str(dest),
        url,
    ]
    if quiet:
        cmd.insert(1, "-sS")
    else:
        cmd.insert(1, "--progress-bar")

    res = subprocess.run(cmd, text=True)  # noqa: S603
    # curl exits 33 when the server refuses a Range request but the file is already whole.
    if res.returncode not in (0, 33):
        raise SystemExit(f"download failed (curl exit {res.returncode})")
    if not dest.exists() or dest.stat().st_size == 0:
        raise SystemExit("download produced no data")

    if _looks_like_html(dest):
        dest.unlink(missing_ok=True)
        raise SystemExit(
            "Drive returned an HTML page, not the file. The file is probably not link-shared.\n"
            "Fix: open it in Drive > Share > General access > 'Anyone with the link'."
        )

    with dest.open("rb") as fh:
        magic = fh.read(2)
    if magic != b"\x1f\x8b":
        raise SystemExit(f"not a gzip archive (magic {magic!r}) — refusing to continue")

    if expected_size and dest.stat().st_size != expected_size:
        raise SystemExit(f"size mismatch: got {dest.stat().st_size:,}, expected {expected_size:,}")

    return Fetched(
        path=dest,
        size=dest.stat().st_size,
        sha256=_sha256(dest),
        declared_uncompressed=_gzip_isize(dest),
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: sdq fetch <drive-url-or-id> [--out PATH] [--expect-size BYTES]", file=sys.stderr)
        return 2

    ref = argv[0]
    out = None
    expect = None
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out = Path(argv[i + 1])
        elif a == "--expect-size" and i + 1 < len(argv):
            expect = int(argv[i + 1])

    dest = out or (DEFAULT_DEST / f"{drive_id(ref)}.tar.gz")
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = fetch(ref, dest, expected_size=expect)
    print()
    print(result.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
