from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlmodel import Session, select

from app.core.paths import static_dir
from app.models.models import (
    AgentConversation,
    AgentMessage,
    Chapter,
    ChapterVersion,
    Character,
    CharacterOutfit,
    CharacterRelationship,
    CharacterState,
    GlobalConfig,
    ImageHistory,
    MemoryEntry,
    Outline,
    Project,
    ProjectProgress,
    SettingCategory,
    SettingEntry,
    SourceChapter,
    SourceImport,
    StoryboardItem,
)

ARCHIVE_FORMAT = "ai-comic-project"
ARCHIVE_VERSION = 1
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
MAX_ARCHIVE_FILES = 10_000
MAX_MANIFEST_RECORDS_PER_TABLE = 50_000
MEDIA_TOP_LEVEL = frozenset({"characters", "panels"})
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

PROJECT_TABLES = {
    "global_configs": GlobalConfig,
    "setting_categories": SettingCategory,
    "setting_entries": SettingEntry,
    "source_imports": SourceImport,
    "source_chapters": SourceChapter,
    "chapters": Chapter,
    "characters": Character,
    "character_outfits": CharacterOutfit,
    "storyboard_items": StoryboardItem,
    "outlines": Outline,
    "memories": MemoryEntry,
    "relationships": CharacterRelationship,
    "character_states": CharacterState,
    "progress": ProjectProgress,
    "chapter_versions": ChapterVersion,
    "image_history": ImageHistory,
    "agent_conversations": AgentConversation,
    "agent_messages": AgentMessage,
}


class ProjectArchiveError(ValueError):
    pass


def _record(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _project_records(session: Session, project_id: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, model in PROJECT_TABLES.items():
        rows = session.exec(select(model).where(model.project_id == project_id)).all()
        data[key] = [_record(row) for row in rows]
    return data


def _safe_filename(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")
    return (name or "project")[:80]


def _media_relative(url: Any, project_id: str) -> PurePosixPath | None:
    """Only accept /static/{project_id}/(characters|panels)/... without traversal."""
    if not isinstance(url, str):
        return None
    prefix = f"/static/{project_id}/"
    if not url.startswith(prefix):
        return None
    relative = PurePosixPath(url[len(prefix):])
    if (
        not relative.parts
        or ".." in relative.parts
        or relative.is_absolute()
        or relative.parts[0] not in MEDIA_TOP_LEVEL
    ):
        return None
    for part in relative.parts:
        if not part or part.endswith((" ", ".")):
            return None
        if part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
            return None
        if "\\" in part or ":" in part:
            return None
    return relative


def _media_member(url: Any, project_id: str) -> tuple[Path, str] | None:
    relative = _media_relative(url, project_id)
    if relative is None:
        return None
    source = (static_dir() / project_id).joinpath(*relative.parts)
    root = (static_dir() / project_id).resolve()
    try:
        resolved = source.resolve(strict=True)
    except FileNotFoundError:
        return None
    if not resolved.is_file() or not resolved.is_relative_to(root):
        return None
    return resolved, (PurePosixPath("media") / relative).as_posix()


def create_project_archive(session: Session, project_id: str) -> tuple[Path, str]:
    project = session.get(Project, project_id)
    if not project:
        raise ProjectArchiveError("Project not found")

    manifest = {
        "format": ARCHIVE_FORMAT,
        "version": ARCHIVE_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "source_project_id": project.id,
        "data": {
            "project": _record(project),
            **_project_records(session, project_id),
        },
    }

    fd, archive_name = tempfile.mkstemp(prefix="ai-comic-project-", suffix=".zip")
    os.close(fd)
    archive_path = Path(archive_name)
    media_urls = {
        record.get(field)
        for key, field in (
            ("characters", "image_url"),
            ("storyboard_items", "image_url"),
            ("character_outfits", "reference_image_url"),
            ("image_history", "image_url"),
        )
        for record in manifest["data"].get(key, [])
    }
    media_files = {
        member
        for url in media_urls
        if (member := _media_member(url, project_id)) is not None
    }

    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for file_path, archive_name in sorted(media_files, key=lambda item: item[1]):
                archive.write(file_path, archive_name)
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise

    return archive_path, f"{_safe_filename(project.title)}.zip"


def _validated_member_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if "\\" in name or ":" in name or name.startswith(("/", "//")):
        raise ProjectArchiveError("ZIP contains an unsafe path")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ProjectArchiveError("ZIP contains an unsafe path")
    for part in path.parts:
        if not part or part.endswith((" ", ".")):
            raise ProjectArchiveError("ZIP contains an unsafe Windows path")
        if part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
            raise ProjectArchiveError("ZIP contains a reserved Windows path")
    if (info.external_attr >> 16) & 0o170000 == 0o120000:
        raise ProjectArchiveError("ZIP symbolic links are not allowed")
    if info.file_size > MAX_MEMBER_BYTES:
        raise ProjectArchiveError("ZIP contains an oversized file")
    if info.file_size and info.compress_size == 0:
        raise ProjectArchiveError("ZIP contains an invalid compressed file")
    if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
        raise ProjectArchiveError("ZIP compression ratio is too high")
    return path.as_posix()


def validate_archive(archive: zipfile.ZipFile) -> dict[str, Any]:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_FILES:
        raise ProjectArchiveError("ZIP contains too many files")
    total_size = 0
    normalized_names = set()
    for info in infos:
        normalized_name = _validated_member_name(info)
        normalized_key = normalized_name.lower()
        if normalized_key in normalized_names:
            raise ProjectArchiveError("ZIP contains duplicate paths")
        normalized_names.add(normalized_key)
        total_size += info.file_size
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise ProjectArchiveError("ZIP uncompressed data is too large")
    try:
        manifest_info = archive.getinfo("manifest.json")
        if manifest_info.file_size > MAX_MANIFEST_BYTES:
            raise ProjectArchiveError("manifest.json is too large")
        raw_manifest = archive.read(manifest_info)
        manifest = json.loads(raw_manifest)
    except KeyError as exc:
        raise ProjectArchiveError("ZIP is missing manifest.json") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectArchiveError("manifest.json is invalid") from exc
    if manifest.get("format") != ARCHIVE_FORMAT:
        raise ProjectArchiveError("Unsupported project ZIP format")
    if manifest.get("version") != ARCHIVE_VERSION:
        raise ProjectArchiveError("Unsupported project ZIP version")
    if not isinstance(manifest.get("data"), dict) or not isinstance(manifest["data"].get("project"), dict):
        raise ProjectArchiveError("Project data is missing from ZIP")
    return manifest


def _base_values(record: dict[str, Any], *excluded: str) -> dict[str, Any]:
    excluded_fields = {"id", "project_id", "created_at", "updated_at", *excluded}
    return {key: value for key, value in record.items() if key not in excluded_fields}


def _rows(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ProjectArchiveError(f"Invalid {key} data")
    if len(value) > MAX_MANIFEST_RECORDS_PER_TABLE:
        raise ProjectArchiveError(f"Too many {key} records")
    if not all(isinstance(item, dict) for item in value):
        raise ProjectArchiveError(f"Invalid {key} records")
    return value


def _remap_media_url(
    url: Any,
    old_project_id: str,
    new_project_id: str,
    *,
    allowed_members: set[str] | None = None,
) -> Any:
    """Remap only safe project media URLs; drop anything else (including external http)."""
    if url is None:
        return None
    if not isinstance(url, str) or not url:
        return None
    relative = _media_relative(url, old_project_id)
    if relative is None:
        # Also accept already-relative paths that match media layout after failed id match? No — drop.
        return None
    member = (PurePosixPath("media") / relative).as_posix()
    if allowed_members is not None and member not in allowed_members:
        return None
    return f"/static/{new_project_id}/{relative.as_posix()}"


def import_project_archive(session: Session, archive_path: Path) -> Project:
    imported_media = {"path": None}
    try:
        return _import_project_archive(
            session,
            archive_path,
            lambda path: imported_media.update(path=path),
        )
    except zipfile.BadZipFile as exc:
        session.rollback()
        if imported_media["path"]:
            shutil.rmtree(imported_media["path"], ignore_errors=True)
        raise ProjectArchiveError("文件不是有效的 ZIP") from exc
    except Exception:
        session.rollback()
        if imported_media["path"]:
            shutil.rmtree(imported_media["path"], ignore_errors=True)
        raise


def _import_project_archive(session: Session, archive_path: Path, remember_media_target) -> Project:
    media_target: Path | None = None
    with zipfile.ZipFile(archive_path, "r") as archive:
        manifest = validate_archive(archive)
        data = manifest["data"]
        project_record = data["project"]
        old_project_id = str(manifest.get("source_project_id") or project_record.get("id") or "")
        if not old_project_id:
            raise ProjectArchiveError("Source project ID is missing")
        new_project_id = str(uuid.uuid4())

        media_infos = [
            info for info in archive.infolist()
            if not info.is_dir() and info.filename.replace("\\", "/").startswith("media/")
        ]
        allowed_media_members: set[str] = set()
        for info in media_infos:
            normalized_name = _validated_member_name(info)
            relative = PurePosixPath(normalized_name)
            try:
                relative = relative.relative_to("media")
            except ValueError as exc:
                raise ProjectArchiveError("ZIP contains an unsupported media path") from exc
            if not relative.parts or relative.parts[0] not in MEDIA_TOP_LEVEL:
                raise ProjectArchiveError("ZIP contains an unsupported media path")
            allowed_media_members.add(normalized_name)

        def remap(url: Any) -> Any:
            return _remap_media_url(
                url, old_project_id, new_project_id, allowed_members=allowed_media_members,
            )

        project_values = _base_values(project_record, "current_chapter_id")
        project = Project(id=new_project_id, current_chapter_id=None, **project_values)
        session.add(project)
        session.flush()

        category_map: dict[int, int] = {}
        source_import_map: dict[int, int] = {}
        source_chapter_map: dict[int, int] = {}
        chapter_map: dict[int, int] = {}
        character_map: dict[int, int] = {}
        outfit_map: dict[int, int] = {}
        storyboard_map: dict[int, int] = {}

        for record in _rows(data, "global_configs"):
            session.add(GlobalConfig(project_id=new_project_id, **_base_values(record)))

        for record in _rows(data, "setting_categories"):
            row = SettingCategory(project_id=new_project_id, **_base_values(record))
            session.add(row)
            session.flush()
            category_map[record["id"]] = row.id
        for record in _rows(data, "setting_entries"):
            values = _base_values(record, "category_id")
            session.add(SettingEntry(project_id=new_project_id, category_id=category_map.get(record.get("category_id")), **values))

        for record in _rows(data, "source_imports"):
            row = SourceImport(project_id=new_project_id, **_base_values(record))
            session.add(row)
            session.flush()
            source_import_map[record["id"]] = row.id
        source_chapter_records = _rows(data, "source_chapters")
        for record in source_chapter_records:
            values = _base_values(record, "source_import_id", "mapped_chapter_id")
            row = SourceChapter(
                project_id=new_project_id,
                source_import_id=source_import_map[record["source_import_id"]],
                mapped_chapter_id=None,
                **values,
            )
            session.add(row)
            session.flush()
            source_chapter_map[record["id"]] = row.id

        chapter_records = _rows(data, "chapters")
        for record in chapter_records:
            values = _base_values(record, "source_chapter_id")
            row = Chapter(
                project_id=new_project_id,
                source_chapter_id=source_chapter_map.get(record.get("source_chapter_id")),
                **values,
            )
            session.add(row)
            session.flush()
            chapter_map[record["id"]] = row.id
        for record in source_chapter_records:
            mapped_id = chapter_map.get(record.get("mapped_chapter_id"))
            if mapped_id:
                row = session.get(SourceChapter, source_chapter_map[record["id"]])
                row.mapped_chapter_id = mapped_id
                session.add(row)

        character_records = _rows(data, "characters")
        for record in character_records:
            values = _base_values(record, "default_outfit_id", "image_url")
            row = Character(
                project_id=new_project_id,
                default_outfit_id=None,
                image_url=remap(record.get("image_url")),
                **values,
            )
            session.add(row)
            session.flush()
            character_map[record["id"]] = row.id
        for record in _rows(data, "character_outfits"):
            values = _base_values(record, "character_id", "reference_image_url")
            row = CharacterOutfit(
                project_id=new_project_id,
                character_id=character_map[record["character_id"]],
                reference_image_url=remap(record.get("reference_image_url")),
                **values,
            )
            session.add(row)
            session.flush()
            outfit_map[record["id"]] = row.id
        for record in character_records:
            default_outfit_id = outfit_map.get(record.get("default_outfit_id"))
            if default_outfit_id:
                row = session.get(Character, character_map[record["id"]])
                row.default_outfit_id = default_outfit_id
                session.add(row)

        for record in _rows(data, "storyboard_items"):
            values = _base_values(record, "chapter_id", "image_url")
            row = StoryboardItem(
                project_id=new_project_id,
                chapter_id=chapter_map.get(record.get("chapter_id")),
                image_url=remap(record.get("image_url")),
                **values,
            )
            session.add(row)
            session.flush()
            storyboard_map[record["id"]] = row.id

        for record in _rows(data, "outlines"):
            values = _base_values(record, "chapter_id")
            session.add(Outline(project_id=new_project_id, chapter_id=chapter_map.get(record.get("chapter_id")), **values))
        for record in _rows(data, "memories"):
            values = _base_values(record, "chapter_id", "character_id")
            session.add(MemoryEntry(
                project_id=new_project_id,
                chapter_id=chapter_map.get(record.get("chapter_id")),
                character_id=character_map.get(record.get("character_id")),
                **values,
            ))
        for record in _rows(data, "relationships"):
            values = _base_values(record, "source_character_id", "target_character_id", "chapter_id")
            session.add(CharacterRelationship(
                project_id=new_project_id,
                source_character_id=character_map[record["source_character_id"]],
                target_character_id=character_map[record["target_character_id"]],
                chapter_id=chapter_map.get(record.get("chapter_id")),
                **values,
            ))
        for record in _rows(data, "character_states"):
            values = _base_values(record, "character_id", "chapter_id", "outfit_id")
            session.add(CharacterState(
                project_id=new_project_id,
                character_id=character_map[record["character_id"]],
                chapter_id=chapter_map.get(record.get("chapter_id")),
                outfit_id=outfit_map.get(record.get("outfit_id")),
                **values,
            ))
        for record in _rows(data, "progress"):
            values = _base_values(record, "current_chapter_id")
            session.add(ProjectProgress(
                project_id=new_project_id,
                current_chapter_id=chapter_map.get(record.get("current_chapter_id")),
                **values,
            ))
        for record in _rows(data, "chapter_versions"):
            values = _base_values(record, "chapter_id")
            session.add(ChapterVersion(project_id=new_project_id, chapter_id=chapter_map[record["chapter_id"]], **values))
        for record in _rows(data, "image_history"):
            values = _base_values(record, "entity_id", "image_url")
            entity_map = character_map if record.get("entity_type") == "character" else storyboard_map
            entity_id = entity_map.get(record.get("entity_id"))
            if entity_id:
                session.add(ImageHistory(
                    project_id=new_project_id,
                    entity_id=entity_id,
                    image_url=remap(record.get("image_url")),
                    **values,
                ))

        conversation_map: dict[int, int] = {}
        for record in _rows(data, "agent_conversations"):
            row = AgentConversation(project_id=new_project_id, **_base_values(record))
            session.add(row)
            session.flush()
            conversation_map[record["id"]] = row.id
        for record in _rows(data, "agent_messages"):
            conversation_id = conversation_map.get(record.get("conversation_id"))
            if not conversation_id:
                continue
            # Tasks are not archived; drop task_id on import.
            values = _base_values(record, "conversation_id", "task_id")
            session.add(AgentMessage(
                project_id=new_project_id,
                conversation_id=conversation_id,
                task_id=None,
                **values,
            ))

        project.current_chapter_id = chapter_map.get(project_record.get("current_chapter_id"))
        session.add(project)

        if media_infos:
            media_target = static_dir() / new_project_id
            if media_target.exists():
                raise ProjectArchiveError("Import media directory already exists")
            media_target.mkdir(parents=True)
            remember_media_target(media_target)
            media_root = media_target.resolve()
            for info in media_infos:
                normalized_name = _validated_member_name(info)
                relative = PurePosixPath(normalized_name).relative_to("media")
                target = media_target.joinpath(*relative.parts)
                resolved_parent = target.parent.resolve()
                if not resolved_parent.is_relative_to(media_root):
                    raise ProjectArchiveError("ZIP media path escapes the project directory")
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(info) as source, target.open("wb") as destination:
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > info.file_size or written > MAX_MEMBER_BYTES:
                            raise ProjectArchiveError("ZIP member expanded beyond its declared size")
                        destination.write(chunk)
                if written != info.file_size:
                    raise ProjectArchiveError("ZIP member size does not match its metadata")

        try:
            session.commit()
            session.refresh(project)
        except Exception:
            session.rollback()
            if media_target:
                shutil.rmtree(media_target, ignore_errors=True)
            raise
        return project
