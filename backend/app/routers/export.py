import os
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.core.database import get_session
from app.core.paths import static_dir
from app.models.models import Project
from app.services.image_service import split_comic_page

router = APIRouter()

MEDIA_TOP_LEVEL = frozenset({"characters", "panels"})
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _safe_export_basename(name: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (name or "").strip(" ."))
    stem = cleaned or fallback
    if stem.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return f"{stem[:80]}.png"


def _resolve_project_media(project_id: str, image_url: str) -> Path | None:
    """Resolve /static/{project_id}/(characters|panels)/... inside the project static root."""
    if not isinstance(image_url, str):
        return None
    prefix = f"/static/{project_id}/"
    if not image_url.startswith(prefix):
        return None
    relative = Path(image_url[len(prefix):].replace("\\", "/"))
    if (
        not relative.parts
        or ".." in relative.parts
        or relative.is_absolute()
        or relative.parts[0] not in MEDIA_TOP_LEVEL
    ):
        return None
    project_root = (static_dir() / project_id).resolve()
    candidate = project_root.joinpath(*relative.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        return None
    if not resolved.is_file() or not resolved.is_relative_to(project_root):
        return None
    return resolved


@router.get("/{project_id}")
def export_project(
    project_id: str,
    split_images: bool = False,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    has_images = any(item.image_url for item in project.storyboard_items) or any(
        c.image_url for c in project.characters
    )
    if not has_images:
        raise HTTPException(status_code=400, detail="No images generated yet. Cannot export.")

    project_static_dir = static_dir() / project_id
    export_dir = project_static_dir / "export"

    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True)

    chars_dir = export_dir / "characters"
    chars_dir.mkdir()
    for char in project.characters:
        if not char.image_url:
            continue
        local_path = _resolve_project_media(project_id, char.image_url)
        if local_path is None:
            continue
        dest_name = _safe_export_basename(char.name, f"character_{char.id}")
        shutil.copy(local_path, chars_dir / dest_name)

    panels_dir = export_dir / "panels"
    if split_images:
        panels_dir.mkdir()

    items = sorted(project.storyboard_items, key=lambda x: x.sequence)

    for item in items:
        if not item.image_url:
            continue
        local_path = _resolve_project_media(project_id, item.image_url)
        if local_path is None:
            continue
        shutil.copy(local_path, export_dir / f"comic_part_{item.sequence}.png")

        if split_images:
            with open(local_path, "rb") as f:
                img_bytes = f.read()
            try:
                panels = split_comic_page(img_bytes)
                for idx, panel_bytes in enumerate(panels):
                    p_name = f"panel_{item.sequence}_{idx + 1}.png"
                    with open(panels_dir / p_name, "wb") as f:
                        f.write(panel_bytes)
            except Exception as e:
                print(f"Failed to split panel {item.id}: {e}")

    zip_path_base = project_static_dir / "export_archive"
    shutil.make_archive(str(zip_path_base), "zip", export_dir)

    return {"download_url": f"/static/{project_id}/export_archive.zip"}
