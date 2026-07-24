# syntax=docker/dockerfile:1

# ---- stage 1: build the frontend ------------------------------------------------
FROM node:20-slim AS frontend-build
WORKDIR /src
COPY webapp/frontend/package.json webapp/frontend/package-lock.json* ./
RUN npm install
COPY webapp/frontend/ ./
RUN npm run build

# ---- stage 2: build the unifiedlog_iterator rust binary (Linux .logarchive support) ----
FROM rust:1-slim-bookworm AS unifiedlog-build
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/mandiant/macos-UnifiedLogs /src/macos-UnifiedLogs
WORKDIR /src/macos-UnifiedLogs/examples/unifiedlog_iterator
# examples/ is its own cargo workspace (see examples/Cargo.toml), so the release binary
# lands in examples/target/release/, not the repo-root target/ — verified by building it.
RUN cargo build --release

# ---- stage 3: runtime -------------------------------------------------------------
FROM python:3.11-slim AS runtime

# graphviz + libmagic1: required by sysdiagnose analysers (coverage graphs, file typing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    graphviz \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=unifiedlog-build /src/macos-UnifiedLogs/examples/target/release/unifiedlog_iterator /usr/local/bin/unifiedlog_iterator

WORKDIR /app

# repo root (the parsing engine) first — changes less often than webapp code, keeps layer caching useful
COPY pyproject.toml README.md LICENSE.txt ./
COPY src ./src

COPY webapp/backend ./webapp/backend
COPY --from=frontend-build /src/dist ./webapp/frontend/dist

WORKDIR /app/webapp/backend
# requirements.txt's `-e ../..` resolves to /app here, i.e. the framework copied above —
# same relative layout as local dev, so this is the one install path for both.
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONUNBUFFERED=1 \
    SYSDX_DATA_ROOT=/data

# /data is where the Railway volume should be mounted (uploads-in-progress + case data)
VOLUME ["/data"]

EXPOSE 8000

# Railway overrides this per-service: the web service uses this default, the worker
# service sets its start command to `python -m app.worker` (see railway.json).
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
