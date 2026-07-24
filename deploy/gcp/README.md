# Deploying sysdx to Google Compute Engine

This directory provisions the **sysdx** webapp (`webapp/`) on a single Google Compute
Engine VM with an attached persistent disk.

## Why a VM (and not a serverless / small-volume PaaS target)

The sysdiagnose framework is filesystem-heavy: it shells out to a native
`unifiedlog_iterator` binary, extracts case trees to disk, writes graphviz output, and
the background worker reads the same local disk the API serves from. It needs real local
storage, sized to real inputs — a single sysdiagnose archive is routinely 100 MB+ and
expands several-fold when extracted and parsed.

A GCE VM + persistent disk gives that with **no artificial per-volume size cap**, which
is the constraint that made a 500 MB PaaS volume unworkable (`OSError: [Errno 28] No
space left on device` mid-parse). The disk here is sized on creation and can be grown
later with no code changes.

## Topology

```
┌────────────────────────── GCE VM (Debian 12, Docker) ──────────────────────────┐
│                                                                                  │
│   sysdx-app  (python -m app.combined: FastAPI + worker thread)  ── :80 ──►  web  │
│       │  SYSDX_DATA_ROOT=/data        SYSDX_DATABASE_URL ─┐                       │
│       ▼                                                   ▼                       │
│   /data/app  (uploads + extracted cases)             sysdx-db (Postgres 16)      │
│       └──────────────── persistent disk /data ───────────┴─ /data/pgdata         │
└──────────────────────────────────────────────────────────────────────────────────┘
```

The API and worker run as **one process/container** (`webapp/backend/app/combined.py`):
the worker loop runs on a background thread, uvicorn on the main thread, so both share
the one local disk trivially — no cross-service shared volume required.

## How the source gets to the VM

The image is built **on the VM**, not locally. The Dockerfile does an in-build
`git clone` (of `macos-UnifiedLogs`, for the Rust log-parsing binary); a VM has clean,
direct internet for that, whereas a build behind a TLS-intercepting egress proxy fails
on the in-container clone. `provision.py` tars the repo, uploads it to a GCS bucket, and
the VM's `startup.sh` pulls + builds it. The VM's default service account is granted
read on that bucket.

## Usage

```sh
pip install google-auth requests

GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa-key.json \
python3 provision.py \
    --project YOUR_PROJECT_ID \
    --repo-root /path/to/sysdiagnose \
    --zone us-central1-a \
    --machine e2-standard-2 \
    --data-gb 20
```

The service-account key needs Compute + Storage admin on the project, and the project
needs billing enabled.

Watch the deploy without SSH — `startup.sh` mirrors progress to a GCS object:

```sh
# gs://sysdx-deploy-<project>/deploy-status.txt   (overwritten as it progresses)
```

When it prints `DEPLOY COMPLETE - app healthy on port 80`, the app is live on the VM's
external IP, port 80.

## Files

| File           | Purpose                                                                    |
|----------------|----------------------------------------------------------------------------|
| `provision.py` | Creates the GCS bucket, data disk, firewall (`:80`), and VM. Idempotent-ish. |
| `startup.sh`   | Runs on the VM: mounts the disk, installs Docker, builds the image, runs Postgres + the app. |

## Secrets

No secrets are committed. `provision.py` generates a random Postgres password at deploy
time and passes it to the VM through instance metadata (`db-password`); `startup.sh`
reads it from the metadata server. The service-account key is supplied out-of-band via
`GOOGLE_APPLICATION_CREDENTIALS` and never written to the repo.

## Notes

- **Verify with a real upload, not just the health check.** The health endpoint coming
  up only proves the process started; it does not prove the disk is big enough. Upload an
  actual sysdiagnose archive and confirm the job reaches `completed` (all steps) before
  declaring the disk sized correctly.
- `yarascan` and `demo_analyser` steps report errors on a stock deploy (no YARA rules
  bundled / demo placeholder); that is expected and does not fail the case.
