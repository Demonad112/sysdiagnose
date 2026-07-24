import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routers import cases, jobs, upload

app = FastAPI(title="sysdx API")

init_db()

app.include_router(upload.router)
app.include_router(cases.router)
app.include_router(jobs.router)

# In dev, the frontend runs on its own Vite dev server and this CORS policy lets it call
# the API directly. In production the built frontend is served from this same process
# (below), so no cross-origin requests happen and this middleware is a no-op.
allowed_origins = os.getenv("SYSDX_CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="frontend-assets")

    # Client-side routing (react-router) means a hard refresh on e.g. /cases/<id> is a
    # real GET for that path with no matching file — StaticFiles(html=True) alone 404s on
    # it. Serve the built index.html for any non-API path instead, so deep links and
    # refreshes work exactly like the SPA's own client-side navigation does.
    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404)
        candidate = _frontend_dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_frontend_dist / "index.html")
