import hmac
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.core.paths import static_dir as resolve_static_dir
from app.routers import configs, projects, generation, export, tasks, history, management, source, assistant

APP_VERSION = "0.2.0"

app = FastAPI(title=settings.PROJECT_NAME)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


@app.middleware("http")
async def require_desktop_token(request: Request, call_next):
    # Packaged desktop always sets COMIC_APP_AUTH_TOKEN. Local `python run_server.py`
    # / pytest leave it unset and stay open for development. Set COMIC_APP_AUTH_REQUIRED=1
    # to force fail-closed auth even without a token (returns 503 until token is configured).
    expected_token = os.environ.get("COMIC_APP_AUTH_TOKEN")
    auth_required = os.environ.get("COMIC_APP_AUTH_REQUIRED", "").lower() in {"1", "true", "yes"}
    protected_path = request.url.path.startswith((settings.API_V1_STR, "/static/"))
    if protected_path and (expected_token or auth_required):
        if not expected_token:
            return JSONResponse(
                status_code=503,
                content={"detail": "Local auth token is required but not configured"},
            )
        supplied_token = request.headers.get("X-Comic-App-Token", "")
        if not hmac.compare_digest(supplied_token, expected_token):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized local request"})
    return await call_next(request)

def frontend_dist_path() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).joinpath("frontend", "dist")
    return Path(__file__).resolve().parents[2].joinpath("frontend", "dist")


# Mount static files
static_dir = resolve_static_dir()
app.mount("/static", StaticFiles(directory=static_dir), name="static")

frontend_dist_dir = frontend_dist_path()
frontend_index_file = frontend_dist_dir / "index.html"
if frontend_index_file.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist_dir / "assets"), name="frontend-assets")

# Include routers
app.include_router(configs.router, prefix=f"{settings.API_V1_STR}/configs", tags=["configs"])
app.include_router(projects.router, prefix=f"{settings.API_V1_STR}/projects", tags=["projects"])
app.include_router(management.router, prefix=f"{settings.API_V1_STR}/projects", tags=["project-management"])
app.include_router(source.router, prefix=settings.API_V1_STR, tags=["source"])
app.include_router(generation.router, prefix=f"{settings.API_V1_STR}/generate", tags=["generation"])
app.include_router(export.router, prefix=f"{settings.API_V1_STR}/export", tags=["export"])
app.include_router(tasks.router, prefix=f"{settings.API_V1_STR}/tasks", tags=["tasks"])
app.include_router(history.router, prefix=f"{settings.API_V1_STR}/history", tags=["history"])
app.include_router(assistant.router, prefix=f"{settings.API_V1_STR}/projects", tags=["assistant"])

@app.on_event("startup")
def on_startup():
    init_db()
    from app.services.task_dispatch import recover_interrupted_tasks

    recover_interrupted_tasks()

@app.get(f"{settings.API_V1_STR}/health")
def health_check():
    return {"status": "ok", "app": settings.PROJECT_NAME, "version": APP_VERSION}


@app.get("/")
def read_root():
    if frontend_index_file.exists():
        return FileResponse(frontend_index_file)
    return {"message": "Welcome to AI Comic Generator API"}


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    if full_path.startswith(("api/", "static/", "docs", "openapi.json", "redoc")):
        raise HTTPException(status_code=404, detail="Not Found")
    if frontend_index_file.exists():
        requested_file = frontend_dist_dir / full_path
        if requested_file.is_file():
            return FileResponse(requested_file)
        return FileResponse(frontend_index_file)
    return {"detail": "Not Found"}
