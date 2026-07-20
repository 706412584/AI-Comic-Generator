import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.core.paths import static_dir as resolve_static_dir
from app.routers import configs, projects, generation, export, tasks, history, management, source

APP_VERSION = "0.2.0"

app = FastAPI(title=settings.PROJECT_NAME)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
