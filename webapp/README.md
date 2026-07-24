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

Railway volumes attach to exactly one service — there's no way to share one volume
between two services the way `web` + `worker` need to share on-disk case data. So on
Railway this deploys as **one service** running `app/combined.py` (the Dockerfile's
default `CMD`): the worker loop runs in a background thread, uvicorn runs in the main
thread, both against the same local disk. Steps:

1. Create one service from this repo/branch (root `railway.json` points it at
   `webapp/Dockerfile`; no start command override needed, the image's default `CMD`
   already runs the combined entrypoint).
2. Attach a volume at `/data`.
3. Add a Postgres plugin to the project and set `SYSDX_DATABASE_URL` to its connection
   string.
4. Set `SYSDX_DATA_ROOT=/data` (see `webapp/.env.example` for the rest).
5. Enable a public domain on the service.

If you deploy somewhere that *does* give you a way to share a filesystem across two
services (a platform with shared/NFS-style volumes, or by running both against S3/object
storage instead of local disk), you can split back into two services and override each
one's start command instead: `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
for the API, `python -m app.worker` for the worker — both still need the same
`SYSDX_DATA_ROOT` and `SYSDX_DATABASE_URL`.
