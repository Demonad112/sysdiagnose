"""``sdq`` entry point.

Only the setup and ingest subcommands exist so far. The query surface
(`map`, `search`, `sql`, `timeline`, `artifact`, ...) is not built yet;
it is listed as "not yet implemented" rather than silently missing so
nobody builds a workflow on a command that does not exist.
"""

from __future__ import annotations

import sys

USAGE = """sdq — interrogate a sysdiagnose

setup
  sdq doctor [--json]              probe capabilities, report blockers
  sdq bootstrap [--skip-unifiedlog]
                                   idempotent environment setup

ingest
  sdq fetch <drive-url-or-id> [--out PATH] [--expect-size N]
                                   resumable HTTPS download of an archive
  sdq ingest <archive.tar.gz> [--case-id ID] [--force]
                                   create the case, extract, survey contents
  sdq status [case_id]             readiness report from what's on disk

not yet implemented
  sdq parse | map | search | sql | timeline | artifact | gaps
"""

PLANNED = {"parse", "map", "search", "sql", "timeline", "artifact", "gaps", "around", "agg", "report"}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(USAGE)
        return 0

    cmd, rest = argv[0], argv[1:]

    if cmd == "doctor":
        from .env import main as run

        return run(rest)
    if cmd == "bootstrap":
        from .bootstrap import main as run

        return run(rest)
    if cmd == "fetch":
        from .fetch_drive import main as run

        return run(rest)
    if cmd == "ingest":
        from .ingest import main as run

        return run(rest)
    if cmd == "status":
        from .status import main as run

        return run(rest)

    if cmd in PLANNED:
        print(f"'{cmd}' is planned but not implemented yet.", file=sys.stderr)
        print("Built so far: doctor, bootstrap, fetch, ingest, status.", file=sys.stderr)
        return 2

    print(f"unknown command: {cmd}\n", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
