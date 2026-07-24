# sysdx webapp

Web UI + API on top of the `sysdiagnose` parsing framework in this repo (`src/sysdiagnose`).
See the root `README.md` for the framework itself.

## Layout

- `backend/` — FastAPI app + background worker (Python, direct-imports `sysdiagnose`)
- `frontend/` — React + Vite + TypeScript SPA

## Architecture

- **Upload**: chunked, resumable (`backend/app/routers/upload.py`). Every chunk streams
  straight to disk; nothing is buffered in memory beyond one chunk (default 8MB). Upload
  state on the frontend lives in a module-level manager
  (`frontend/src/lib/uploadManager.ts`), not in React component state, so a route change,
  re-render, or thrown error in the page tree can't wipe out an in-flight upload —
  this is the actual fix for the original prototype's "folder + files together
  sometimes wipes all progress" bug.
- **Processing**: on upload completion, a `Job` row is queued. `backend/app/worker.py`
  polls that table and spawns one `python -m app.case_runner` subprocess per job.
  `case_runner.py` directly imports the `Sysdiagnose` class and runs `create_case` +
  every parser + every analyser, writing per-step progress to the DB as it goes. The
  subprocess boundary exists purely for fault isolation (a native-code crash in one
  parser only kills that job, not the worker daemon) — everything inside it still talks
  to the framework via its Python API, not the CLI.
  - Files no parser claims (via `get_log_files()`) are written to `_unparsed.json` per
    case instead of being dropped, and served as the "Unparsed / Raw" nav section.
- **Queue**: a Postgres/SQLite `jobs` + `parser_progress` table, no Redis/Celery — see
  `backend/app/worker.py` docstring for the reasoning.
- **Data retrieval**: `backend/app/services/data_service.py` reads parser/analyser output
  straight from `<case>/parsed_data/` on disk (the framework's own cache); the API never
  re-runs a parser on read.
- **Rendering**: one dispatch component (`frontend/src/components/ModuleOutput.tsx`)
  picks Timeline / DataTable / KeyValueCard / RawViewer per module based on its declared
  `format` (`jsonl` → timeline, list-of-dicts → table, dict → key-value, anything else →
  raw text + download) — this is what covers all ~57 parsers/analysers without a
  bespoke renderer per module. Category grouping for the sidebar nav is the single
  source of truth in `backend/app/categories.py` and is served to the frontend via
  `/api/meta/parsers`, not duplicated in TypeScript.

## Local development

```bash
# from the repo root
pip install -e .
cd webapp/backend
pip install -r requirements.txt
SYSDX_DATA_ROOT=./data uvicorn app.main:app --reload --port 8000 &
SYSDX_DATA_ROOT=./data python -m app.worker &

cd ../frontend
npm install
npm run dev   # proxies /api to :8000, open http://localhost:5173
```

For `.logarchive` parsing on Linux you also need the `unifiedlog_iterator` binary on
`PATH` — see the root README's "UnifiedLogs" section for the `cargo build` steps (the
Dockerfile builds this automatically for deploy).

## Deploying to Railway

The root `railway.json` builds `webapp/Dockerfile`, which produces one image containing
both the API and the worker entrypoint. Set up **two services** from that same image in
one Railway project:

1. **`web`** — uses `railway.json` as-is (`uvicorn app.main:app`), attach the shared
   volume at `/data`, expose it publicly.
2. **`worker`** — same repo/Dockerfile, but override the start command to
   `python -m app.worker`. Attach the *same* volume at `/data`, no public networking
   needed.

Both services need the same environment variables (see `webapp/.env.example`):
`SYSDX_DATA_ROOT=/data`, `SYSDX_DATABASE_URL` pointed at a Railway Postgres plugin
attached to the project, and `SYSDX_CORS_ORIGINS` (only relevant if you ever split the
frontend into its own service — by default `web` serves the built frontend itself).

Add a Postgres plugin to the project and set `SYSDX_DATABASE_URL` on both services to its
connection string (SQLite is only used as the zero-config local-dev fallback).
