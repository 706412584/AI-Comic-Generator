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
    SourceImport,
    Task,
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
        {
            "type": "function",
            "function": {
                "name": "start_project_initialization",
                "description": "派发「一句话初始化」后台任务：为空项目生成设定/角色/大纲/章节规划。项目已有内容时会失败。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_input": {
                            "type": "string",
                            "description": "一句话核心创意，必填",
                        },
                    },
                    "required": ["user_input"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "start_generate_all_images",
                "description": "派发批量出图任务（角色缺图补画 + 分镜面板图）。耗时，完成后看任务管理器。",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "start_generate_all_characters",
                "description": "派发批量角色立绘任务（会覆盖已有角色图）。",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "start_chapter_content",
                "description": "派发章节正文生成任务。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chapter_id": {"type": "integer"},
                        "user_input": {"type": "string", "description": "可选补充要求"},
                    },
                    "required": ["chapter_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "start_chapter_storyboard",
                "description": "派发章节分镜生成任务（把章节正文改写成分镜）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chapter_id": {"type": "integer"},
                        "user_input": {"type": "string", "description": "可选补充要求"},
                    },
                    "required": ["chapter_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "start_source_analysis",
                "description": "派发原文分析任务（需已导入小说原文）。mode: continue|restart|all",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "description": "continue（默认）| restart | all",
                        },
                        "max_chapters": {
                            "type": "integer",
                            "description": "continue/restart 时最多分析章数，默认 50；mode=all 时忽略",
                        },
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
    if name not in TOOL_HANDLERS:
        raise ToolError(f"工具未注册 handler: {name}")

    handler: Callable[[Session, str, dict[str, Any]], Any] = TOOL_HANDLERS[name]
    try:
        # 清理上一轮残留的派发队列
        session.info.pop("assistant_dispatch_queue", None)
        result = handler(session, project_id, args)
        queue = list(session.info.pop("assistant_dispatch_queue", []) or [])
        session.commit()
        for task_id, task_type, payload in queue:
            _enqueue_task(task_id, task_type, payload)
        return _dump_json({"ok": True, "tool": name, "result": result})
    except ToolError:
        session.info.pop("assistant_dispatch_queue", None)
        session.rollback()
        raise
    except Exception as exc:
        session.info.pop("assistant_dispatch_queue", None)
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


def _has_running_task(session: Session, project_id: str, task_type: str) -> bool:
    return (
        session.exec(
            select(Task).where(
                Task.project_id == project_id,
                Task.type == task_type,
                Task.status.in_(["pending", "processing"]),
            )
        ).first()
        is not None
    )


def _enqueue_task(task_id: str, task_type: str, payload: dict[str, Any]) -> None:
    """在独立线程执行 run_task，避免阻塞助手 tool loop。"""
    import threading

    from app.services.task_dispatch import run_task

    def _worker() -> None:
        try:
            run_task(task_id, task_type, payload)
        except Exception:
            # run_task / runner 自行写 failed；这里只防止线程异常吞掉
            pass

    threading.Thread(target=_worker, daemon=True, name=f"assistant-dispatch-{task_type}").start()


def _handle_start_project_initialization(
    session: Session, project_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    from app.routers.generation import has_initialized_content, has_running_project_initialization

    _require_project(session, project_id)
    user_input = str(args.get("user_input") or "").strip()
    if not user_input:
        raise ToolError("user_input 不能为空")
    if has_initialized_content(session, project_id):
        raise ToolError("项目已有设定/角色/章节/大纲/记忆，无法一句话初始化；请用空项目或手动编辑")
    if has_running_project_initialization(session, project_id):
        raise ToolError("项目初始化任务已在运行中")

    project = session.get(Project, project_id)
    project.story_input = user_input
    session.add(project)

    task = Task(
        type="project_initialization",
        status="pending",
        project_id=project_id,
        name="一句话初始化项目",
        description="AI 正在生成设定、角色、关系、大纲和章节规划",
        progress=0,
        message="等待 AI 初始化...",
        input_payload={"project_id": project_id, "user_input": user_input},
    )
    session.add(task)
    session.flush()
    task_id = task.id
    payload = dict(task.input_payload or {})
    # commit 由 execute_tool 统一完成；标记需在 commit 后入队
    session.info.setdefault("assistant_dispatch_queue", []).append(
        (task_id, "project_initialization", payload)
    )
    return {
        "task_id": task_id,
        "task_type": "project_initialization",
        "message": "已派发一句话初始化任务，请在右下角任务面板查看进度",
    }


def _handle_start_generate_all_images(
    session: Session, project_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    _require_project(session, project_id)
    if _has_running_task(session, project_id, "image_generation"):
        raise ToolError("已有批量出图任务在运行")
    task = Task(
        type="image_generation",
        status="pending",
        project_id=project_id,
        name="Batch Generate Images",
        description="Generating all storyboard images",
        input_payload={"project_id": project_id},
    )
    session.add(task)
    session.flush()
    payload = dict(task.input_payload or {})
    session.info.setdefault("assistant_dispatch_queue", []).append(
        (task.id, "image_generation", payload)
    )
    return {
        "task_id": task.id,
        "task_type": "image_generation",
        "message": "已派发批量出图任务",
    }


def _handle_start_generate_all_characters(
    session: Session, project_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    _require_project(session, project_id)
    if _has_running_task(session, project_id, "character_generation"):
        raise ToolError("已有角色绘制任务在运行")
    task = Task(
        type="character_generation",
        status="pending",
        project_id=project_id,
        name="Batch Generate Characters",
        description="Generating all character design sheets",
        input_payload={"project_id": project_id},
    )
    session.add(task)
    session.flush()
    payload = dict(task.input_payload or {})
    session.info.setdefault("assistant_dispatch_queue", []).append(
        (task.id, "character_generation", payload)
    )
    return {
        "task_id": task.id,
        "task_type": "character_generation",
        "message": "已派发批量角色绘制任务",
    }


def _handle_start_chapter_content(
    session: Session, project_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    chapter_id = int(args.get("chapter_id") or 0)
    chapter = _chapter_in_project(session, project_id, chapter_id)
    user_input = str(args.get("user_input") or "")
    task = Task(
        type="chapter_content_generation",
        status="pending",
        project_id=project_id,
        name=f"生成章节正文: {chapter.title or chapter_id}",
        description="AI 正在生成章节正文",
        progress=0,
        message="等待生成章节正文...",
        scope_type="chapter",
        scope_id=str(chapter_id),
        input_payload={
            "project_id": project_id,
            "chapter_id": chapter_id,
            "user_input": user_input,
            "save_version": True,
        },
    )
    session.add(task)
    session.flush()
    payload = dict(task.input_payload or {})
    session.info.setdefault("assistant_dispatch_queue", []).append(
        (task.id, "chapter_content_generation", payload)
    )
    return {
        "task_id": task.id,
        "task_type": "chapter_content_generation",
        "chapter_id": chapter_id,
        "message": "已派发章节正文生成任务",
    }


def _handle_start_chapter_storyboard(
    session: Session, project_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    chapter_id = int(args.get("chapter_id") or 0)
    chapter = _chapter_in_project(session, project_id, chapter_id)
    user_input = str(args.get("user_input") or "")
    task = Task(
        type="chapter_storyboard",
        status="pending",
        project_id=project_id,
        name=f"章节分镜: {chapter.title or chapter_id}",
        description="AI 正在生成章节分镜",
        progress=0,
        message="等待生成章节分镜...",
        scope_type="chapter",
        scope_id=str(chapter_id),
        input_payload={
            "project_id": project_id,
            "chapter_id": chapter_id,
            "user_input": user_input,
        },
    )
    session.add(task)
    session.flush()
    payload = dict(task.input_payload or {})
    session.info.setdefault("assistant_dispatch_queue", []).append(
        (task.id, "chapter_storyboard", payload)
    )
    return {
        "task_id": task.id,
        "task_type": "chapter_storyboard",
        "chapter_id": chapter_id,
        "message": "已派发章节分镜任务",
    }


def _handle_start_source_analysis(
    session: Session, project_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    _require_project(session, project_id)
    mode = str(args.get("mode") or "continue").strip() or "continue"
    if mode not in {"continue", "restart", "all"}:
        raise ToolError("mode 必须是 continue / restart / all")
    source_import = session.exec(
        select(SourceImport)
        .where(SourceImport.project_id == project_id)
        .order_by(SourceImport.created_at.desc())
    ).first()
    if not source_import:
        raise ToolError("请先导入小说原文")
    if _has_running_task(session, project_id, "source_analysis"):
        raise ToolError("原文分析任务已在运行中")

    max_chapters = None if mode == "all" else int(args.get("max_chapters") or 50)
    task = Task(
        type="source_analysis",
        status="pending",
        project_id=project_id,
        name="原文分析",
        description="AI 正在分析原文章节并生成全书摘要",
        progress=0,
        message="等待原文分析...",
        input_payload={
            "project_id": project_id,
            "max_chapters": max_chapters,
            "mode": mode,
        },
    )
    session.add(task)
    session.flush()
    payload = dict(task.input_payload or {})
    session.info.setdefault("assistant_dispatch_queue", []).append(
        (task.id, "source_analysis", payload)
    )
    return {
        "task_id": task.id,
        "task_type": "source_analysis",
        "mode": mode,
        "message": "已派发原文分析任务",
    }


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
    "start_project_initialization": _handle_start_project_initialization,
    "start_generate_all_images": _handle_start_generate_all_images,
    "start_generate_all_characters": _handle_start_generate_all_characters,
    "start_chapter_content": _handle_start_chapter_content,
    "start_chapter_storyboard": _handle_start_chapter_storyboard,
    "start_source_analysis": _handle_start_source_analysis,
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
