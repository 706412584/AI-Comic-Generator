from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable

from sqlmodel import Session, select

from app.models.models import (
    Chapter,
    Character,
    MemoryEntry,
    Outline,
    Project,
    ProjectProgress,
    SettingCategory,
    SettingEntry,
)

MAX_TOOL_RESULT_CHARS = 12000
MAX_SEARCH_RESULTS = 20
MAX_TEXT_FIELD = 20000


class ToolError(ValueError):
    pass


def _clip(value: Any, max_len: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _require_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise ToolError("Project not found")
    return project


def _chapter_in_project(session: Session, project_id: str, chapter_id: int) -> Chapter:
    chapter = session.get(Chapter, chapter_id)
    if not chapter or chapter.project_id != project_id:
        raise ToolError(f"Chapter not found: {chapter_id}")
    return chapter


def _setting_in_project(session: Session, project_id: str, setting_id: int) -> SettingEntry:
    entry = session.get(SettingEntry, setting_id)
    if not entry or entry.project_id != project_id:
        raise ToolError(f"Setting not found: {setting_id}")
    return entry


def _character_in_project(session: Session, project_id: str, character_id: int) -> Character:
    character = session.get(Character, character_id)
    if not character or character.project_id != project_id:
        raise ToolError(f"Character not found: {character_id}")
    return character


def _outline_in_project(session: Session, project_id: str, outline_id: int) -> Outline:
    outline = session.get(Outline, outline_id)
    if not outline or outline.project_id != project_id:
        raise ToolError(f"Outline not found: {outline_id}")
    return outline


def _memory_in_project(session: Session, project_id: str, memory_id: int) -> MemoryEntry:
    memory = session.get(MemoryEntry, memory_id)
    if not memory or memory.project_id != project_id:
        raise ToolError(f"Memory not found: {memory_id}")
    return memory


def _match_query(text: str, query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return True
    return q in (text or "").lower()


def _dump_json(data: Any) -> str:
    raw = json.dumps(data, ensure_ascii=False, default=str)
    if len(raw) > MAX_TOOL_RESULT_CHARS:
        return raw[: MAX_TOOL_RESULT_CHARS - 20] + '…"}'
    return raw


def openai_tool_definitions() -> list[dict[str, Any]]:
    """OpenAI-compatible tools schema (function calling)."""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_project",
                "description": "读取当前项目基础信息（标题、描述、主题、工作流等）",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_chapters",
                "description": "列出项目章节（id/序号/标题/摘要/状态），不含全文",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "最多返回条数，默认 50，最大 100"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_chapter",
                "description": "读取某一章节详情，可选包含正文",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chapter_id": {"type": "integer"},
                        "include_content": {"type": "boolean", "description": "是否包含正文，默认 true"},
                    },
                    "required": ["chapter_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_settings",
                "description": "按关键词搜索设定条目（标题/内容/标签）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_characters",
                "description": "按关键词搜索角色（名称/别名/摘要）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_outlines",
                "description": "列出大纲条目",
                "parameters": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer"}},
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_memories",
                "description": "搜索记忆库条目",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_progress",
                "description": "读取项目当前进度状态",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_project",
                "description": "更新项目基础字段（标题/描述/主题/故事输入等）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "theme": {"type": "string"},
                        "story_input": {"type": "string"},
                        "language": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_chapter",
                "description": "更新已有章节字段（标题/摘要/正文/目标/冲突等）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chapter_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "content": {"type": "string"},
                        "goal": {"type": "string"},
                        "conflict": {"type": "string"},
                        "status": {"type": "string"},
                        "current_location": {"type": "string"},
                        "current_time": {"type": "string"},
                        "pov_character": {"type": "string"},
                    },
                    "required": ["chapter_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_chapter",
                "description": "新建章节",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "sequence": {"type": "integer", "description": "可选，默认追加到末尾"},
                        "summary": {"type": "string"},
                        "content": {"type": "string"},
                        "goal": {"type": "string"},
                        "conflict": {"type": "string"},
                    },
                    "required": ["title"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_setting",
                "description": "新建设定条目；可选 category_name 自动找/建分类",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "category_name": {"type": "string"},
                        "importance": {"type": "integer"},
                    },
                    "required": ["title", "content"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_setting",
                "description": "更新设定条目",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "setting_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "importance": {"type": "integer"},
                        "is_active": {"type": "boolean"},
                    },
                    "required": ["setting_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_character",
                "description": "新建角色",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "summary": {"type": "string"},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "data": {"type": "object", "description": "角色设定 JSON，如 personality/appearance"},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_character",
                "description": "更新角色名称/摘要/别名/data",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "character_id": {"type": "integer"},
                        "name": {"type": "string"},
                        "summary": {"type": "string"},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string"},
                        "data": {"type": "object"},
                    },
                    "required": ["character_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_outline",
                "description": "新建大纲条目",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "chapter_id": {"type": "integer"},
                        "scope": {"type": "string"},
                        "sort_order": {"type": "integer"},
                    },
                    "required": ["title", "content"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_outline",
                "description": "更新大纲条目",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "outline_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "sort_order": {"type": "integer"},
                    },
                    "required": ["outline_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_memory",
                "description": "写入一条记忆",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "scope": {"type": "string"},
                        "memory_type": {"type": "string"},
                        "chapter_id": {"type": "integer"},
                        "character_id": {"type": "integer"},
                    },
                    "required": ["content"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_progress",
                "description": "更新项目进度（当前弧线/地点/时间/主冲突/备注等）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "current_chapter_id": {"type": "integer"},
                        "current_arc": {"type": "string"},
                        "current_location": {"type": "string"},
                        "current_time": {"type": "string"},
                        "main_conflict": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        },
    ]


def tool_names() -> set[str]:
    return {item["function"]["name"] for item in openai_tool_definitions()}


def execute_tool(session: Session, project_id: str, name: str, arguments: dict[str, Any] | None) -> str:
    args = arguments or {}
    if not isinstance(args, dict):
        raise ToolError("工具参数必须是 JSON 对象")
    if name not in tool_names():
        raise ToolError(f"未知工具: {name}")

    handler: Callable[[Session, str, dict[str, Any]], Any] = TOOL_HANDLERS[name]
    try:
        result = handler(session, project_id, args)
        session.commit()
        return _dump_json({"ok": True, "tool": name, "result": result})
    except ToolError:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise ToolError(str(exc)) from exc


def _handle_get_project(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    project = _require_project(session, project_id)
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "theme": project.theme,
        "language": project.language,
        "workflow_mode": project.workflow_mode,
        "story_input": _clip(project.story_input, 1000),
        "current_chapter_id": project.current_chapter_id,
        "panel_count": project.panel_count,
        "aspect_ratio": project.aspect_ratio,
        "resolution": project.resolution,
    }


def _handle_list_chapters(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_project(session, project_id)
    limit = int(args.get("limit") or 50)
    limit = max(1, min(limit, 100))
    chapters = session.exec(
        select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.sequence)
    ).all()
    items = [
        {
            "id": c.id,
            "sequence": c.sequence,
            "title": c.title,
            "summary": _clip(c.summary, 200),
            "status": c.status,
            "word_count": c.word_count,
        }
        for c in chapters[:limit]
    ]
    return {"total": len(chapters), "items": items}


def _handle_get_chapter(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    chapter_id = int(args["chapter_id"])
    chapter = _chapter_in_project(session, project_id, chapter_id)
    include_content = args.get("include_content", True)
    data = {
        "id": chapter.id,
        "sequence": chapter.sequence,
        "title": chapter.title,
        "summary": chapter.summary,
        "goal": chapter.goal,
        "conflict": chapter.conflict,
        "status": chapter.status,
        "current_location": chapter.current_location,
        "current_time": chapter.current_time,
        "pov_character": chapter.pov_character,
        "word_count": chapter.word_count,
    }
    if include_content:
        content = chapter.content or ""
        data["content"] = content if len(content) <= MAX_TEXT_FIELD else content[:MAX_TEXT_FIELD] + "…"
    return data


def _handle_search_settings(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_project(session, project_id)
    query = str(args.get("query") or "")
    limit = max(1, min(int(args.get("limit") or 10), MAX_SEARCH_RESULTS))
    entries = session.exec(select(SettingEntry).where(SettingEntry.project_id == project_id)).all()
    matched = []
    for entry in entries:
        blob = f"{entry.title}\n{entry.content}\n{' '.join(entry.tags or [])}"
        if _match_query(blob, query):
            matched.append(
                {
                    "id": entry.id,
                    "title": entry.title,
                    "content": _clip(entry.content, 400),
                    "category_id": entry.category_id,
                    "importance": entry.importance,
                    "is_active": entry.is_active,
                }
            )
        if len(matched) >= limit:
            break
    return {"query": query, "count": len(matched), "items": matched}


def _handle_search_characters(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_project(session, project_id)
    query = str(args.get("query") or "")
    limit = max(1, min(int(args.get("limit") or 10), MAX_SEARCH_RESULTS))
    characters = session.exec(select(Character).where(Character.project_id == project_id)).all()
    matched = []
    for character in characters:
        blob = f"{character.name}\n{character.summary or ''}\n{' '.join(character.aliases or [])}"
        if _match_query(blob, query):
            matched.append(
                {
                    "id": character.id,
                    "name": character.name,
                    "summary": _clip(character.summary, 300),
                    "aliases": character.aliases or [],
                    "status": character.status,
                    "data": character.data or {},
                }
            )
        if len(matched) >= limit:
            break
    return {"query": query, "count": len(matched), "items": matched}


def _handle_list_outlines(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_project(session, project_id)
    limit = max(1, min(int(args.get("limit") or 30), 100))
    outlines = session.exec(
        select(Outline).where(Outline.project_id == project_id).order_by(Outline.sort_order)
    ).all()
    items = [
        {
            "id": o.id,
            "title": o.title,
            "content": _clip(o.content, 300),
            "chapter_id": o.chapter_id,
            "scope": o.scope,
            "sort_order": o.sort_order,
        }
        for o in outlines[:limit]
    ]
    return {"total": len(outlines), "items": items}


def _handle_search_memories(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_project(session, project_id)
    query = str(args.get("query") or "")
    limit = max(1, min(int(args.get("limit") or 10), MAX_SEARCH_RESULTS))
    memories = session.exec(select(MemoryEntry).where(MemoryEntry.project_id == project_id)).all()
    matched = []
    for memory in memories:
        if _match_query(memory.content or "", query):
            matched.append(
                {
                    "id": memory.id,
                    "content": _clip(memory.content, 400),
                    "scope": memory.scope,
                    "memory_type": getattr(memory, "memory_type", None),
                    "chapter_id": memory.chapter_id,
                    "character_id": memory.character_id,
                }
            )
        if len(matched) >= limit:
            break
    return {"query": query, "count": len(matched), "items": matched}


def _handle_get_progress(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_project(session, project_id)
    progress = session.exec(
        select(ProjectProgress).where(ProjectProgress.project_id == project_id)
    ).first()
    if not progress:
        return {"exists": False}
    return {
        "exists": True,
        "current_chapter_id": progress.current_chapter_id,
        "current_arc": progress.current_arc,
        "current_location": progress.current_location,
        "current_time": progress.current_time,
        "main_conflict": progress.main_conflict,
        "notes": progress.notes,
        "active_threads": progress.active_threads or [],
        "resolved_threads": progress.resolved_threads or [],
        "pending_hooks": progress.pending_hooks or [],
    }


def _handle_update_project(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    project = _require_project(session, project_id)
    allowed = ("title", "description", "theme", "story_input", "language")
    changed = []
    for key in allowed:
        if key in args and args[key] is not None:
            value = args[key]
            if isinstance(value, str) and len(value) > MAX_TEXT_FIELD:
                raise ToolError(f"{key} 过长")
            if key == "title" and not str(value).strip():
                raise ToolError("title 不能为空")
            setattr(project, key, value)
            changed.append(key)
    if not changed:
        raise ToolError("未提供可更新字段")
    project.updated_at = datetime.utcnow()
    session.add(project)
    return {"updated_fields": changed, "id": project.id, "title": project.title}


def _handle_update_chapter(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    chapter = _chapter_in_project(session, project_id, int(args["chapter_id"]))
    allowed = (
        "title", "summary", "content", "goal", "conflict", "status",
        "current_location", "current_time", "pov_character",
    )
    changed = []
    for key in allowed:
        if key in args and args[key] is not None:
            value = args[key]
            if isinstance(value, str) and len(value) > MAX_TEXT_FIELD:
                raise ToolError(f"{key} 过长")
            setattr(chapter, key, value)
            changed.append(key)
    if "content" in changed:
        chapter.word_count = len(chapter.content or "")
    if not changed:
        raise ToolError("未提供可更新字段")
    chapter.updated_at = datetime.utcnow()
    session.add(chapter)
    return {"updated_fields": changed, "id": chapter.id, "title": chapter.title}


def _handle_create_chapter(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_project(session, project_id)
    title = str(args.get("title") or "").strip()
    if not title:
        raise ToolError("title 不能为空")
    if args.get("sequence") is not None:
        sequence = int(args["sequence"])
    else:
        existing = session.exec(
            select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.sequence.desc())
        ).first()
        sequence = (existing.sequence + 1) if existing else 1
    content = args.get("content")
    chapter = Chapter(
        project_id=project_id,
        sequence=sequence,
        title=title,
        summary=args.get("summary"),
        content=content,
        goal=args.get("goal"),
        conflict=args.get("conflict"),
        word_count=len(content or ""),
    )
    session.add(chapter)
    session.flush()
    return {"id": chapter.id, "sequence": chapter.sequence, "title": chapter.title}


def _ensure_category(session: Session, project_id: str, name: str | None) -> int | None:
    if not name or not str(name).strip():
        return None
    name = str(name).strip()
    existing = session.exec(
        select(SettingCategory)
        .where(SettingCategory.project_id == project_id)
        .where(SettingCategory.name == name)
    ).first()
    if existing:
        return existing.id
    category = SettingCategory(project_id=project_id, name=name, description="")
    session.add(category)
    session.flush()
    return category.id


def _handle_create_setting(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_project(session, project_id)
    title = str(args.get("title") or "").strip()
    content = str(args.get("content") or "").strip()
    if not title or not content:
        raise ToolError("title 与 content 均不能为空")
    if len(content) > MAX_TEXT_FIELD:
        raise ToolError("content 过长")
    category_id = _ensure_category(session, project_id, args.get("category_name"))
    entry = SettingEntry(
        project_id=project_id,
        category_id=category_id,
        title=title,
        content=content,
        importance=int(args.get("importance") or 3),
    )
    session.add(entry)
    session.flush()
    return {"id": entry.id, "title": entry.title, "category_id": entry.category_id}


def _handle_update_setting(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    entry = _setting_in_project(session, project_id, int(args["setting_id"]))
    changed = []
    for key in ("title", "content", "importance", "is_active"):
        if key in args and args[key] is not None:
            value = args[key]
            if key in {"title", "content"} and isinstance(value, str) and len(value) > MAX_TEXT_FIELD:
                raise ToolError(f"{key} 过长")
            setattr(entry, key, value)
            changed.append(key)
    if not changed:
        raise ToolError("未提供可更新字段")
    entry.updated_at = datetime.utcnow()
    session.add(entry)
    return {"id": entry.id, "updated_fields": changed, "title": entry.title}


def _handle_create_character(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_project(session, project_id)
    name = str(args.get("name") or "").strip()
    if not name:
        raise ToolError("name 不能为空")
    data = args.get("data") if isinstance(args.get("data"), dict) else {}
    aliases = args.get("aliases") if isinstance(args.get("aliases"), list) else []
    character = Character(
        project_id=project_id,
        name=name,
        summary=args.get("summary"),
        aliases=[str(a) for a in aliases],
        data=data,
    )
    session.add(character)
    session.flush()
    return {"id": character.id, "name": character.name}


def _handle_update_character(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    character = _character_in_project(session, project_id, int(args["character_id"]))
    changed = []
    if "name" in args and args["name"] is not None:
        name = str(args["name"]).strip()
        if not name:
            raise ToolError("name 不能为空")
        character.name = name
        changed.append("name")
    if "summary" in args and args["summary"] is not None:
        character.summary = args["summary"]
        changed.append("summary")
    if "status" in args and args["status"] is not None:
        character.status = args["status"]
        changed.append("status")
    if "aliases" in args and args["aliases"] is not None:
        if not isinstance(args["aliases"], list):
            raise ToolError("aliases 必须是数组")
        character.aliases = [str(a) for a in args["aliases"]]
        changed.append("aliases")
    if "data" in args and args["data"] is not None:
        if not isinstance(args["data"], dict):
            raise ToolError("data 必须是对象")
        # merge shallow
        merged = dict(character.data or {})
        merged.update(args["data"])
        character.data = merged
        changed.append("data")
    if not changed:
        raise ToolError("未提供可更新字段")
    session.add(character)
    return {"id": character.id, "name": character.name, "updated_fields": changed}


def _handle_create_outline(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_project(session, project_id)
    title = str(args.get("title") or "").strip()
    content = str(args.get("content") or "").strip()
    if not title or not content:
        raise ToolError("title 与 content 均不能为空")
    chapter_id = args.get("chapter_id")
    if chapter_id is not None:
        _chapter_in_project(session, project_id, int(chapter_id))
        chapter_id = int(chapter_id)
    outline = Outline(
        project_id=project_id,
        title=title,
        content=content,
        chapter_id=chapter_id,
        scope=str(args.get("scope") or "project"),
        sort_order=int(args.get("sort_order") or 0),
    )
    session.add(outline)
    session.flush()
    return {"id": outline.id, "title": outline.title}


def _handle_update_outline(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    outline = _outline_in_project(session, project_id, int(args["outline_id"]))
    changed = []
    for key in ("title", "content", "sort_order"):
        if key in args and args[key] is not None:
            setattr(outline, key, args[key])
            changed.append(key)
    if not changed:
        raise ToolError("未提供可更新字段")
    outline.updated_at = datetime.utcnow()
    session.add(outline)
    return {"id": outline.id, "updated_fields": changed}


def _handle_create_memory(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_project(session, project_id)
    content = str(args.get("content") or "").strip()
    if not content:
        raise ToolError("content 不能为空")
    chapter_id = args.get("chapter_id")
    character_id = args.get("character_id")
    if chapter_id is not None:
        _chapter_in_project(session, project_id, int(chapter_id))
        chapter_id = int(chapter_id)
    if character_id is not None:
        _character_in_project(session, project_id, int(character_id))
        character_id = int(character_id)
    memory = MemoryEntry(
        project_id=project_id,
        content=content,
        scope=str(args.get("scope") or "project"),
        memory_type=str(args.get("memory_type") or "event"),
        chapter_id=chapter_id,
        character_id=character_id,
    )
    session.add(memory)
    session.flush()
    return {"id": memory.id, "content": _clip(memory.content, 200)}


def _handle_update_progress(session: Session, project_id: str, args: dict[str, Any]) -> dict[str, Any]:
    _require_project(session, project_id)
    progress = session.exec(
        select(ProjectProgress).where(ProjectProgress.project_id == project_id)
    ).first()
    if not progress:
        progress = ProjectProgress(project_id=project_id)
        session.add(progress)
        session.flush()
    changed = []
    if "current_chapter_id" in args and args["current_chapter_id"] is not None:
        chapter_id = int(args["current_chapter_id"])
        _chapter_in_project(session, project_id, chapter_id)
        progress.current_chapter_id = chapter_id
        changed.append("current_chapter_id")
    for key in ("current_arc", "current_location", "current_time", "main_conflict", "notes"):
        if key in args and args[key] is not None:
            setattr(progress, key, args[key])
            changed.append(key)
    if not changed:
        raise ToolError("未提供可更新字段")
    progress.updated_at = datetime.utcnow()
    session.add(progress)
    return {"updated_fields": changed}


TOOL_HANDLERS: dict[str, Callable[[Session, str, dict[str, Any]], Any]] = {
    "get_project": _handle_get_project,
    "list_chapters": _handle_list_chapters,
    "get_chapter": _handle_get_chapter,
    "search_settings": _handle_search_settings,
    "search_characters": _handle_search_characters,
    "list_outlines": _handle_list_outlines,
    "search_memories": _handle_search_memories,
    "get_progress": _handle_get_progress,
    "update_project": _handle_update_project,
    "update_chapter": _handle_update_chapter,
    "create_chapter": _handle_create_chapter,
    "create_setting": _handle_create_setting,
    "update_setting": _handle_update_setting,
    "create_character": _handle_create_character,
    "update_character": _handle_update_character,
    "create_outline": _handle_create_outline,
    "update_outline": _handle_update_outline,
    "create_memory": _handle_create_memory,
    "update_progress": _handle_update_progress,
}


def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            # try repair trailing commas lightly
            repaired = re.sub(r",\s*}", "}", text)
            repaired = re.sub(r",\s*]", "]", repaired)
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError:
                raise ToolError(f"工具参数 JSON 无效: {exc}") from exc
        if not isinstance(data, dict):
            raise ToolError("工具参数必须是 JSON 对象")
        return data
    raise ToolError("工具参数类型无效")
