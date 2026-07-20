from typing import Any, Dict

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.database import get_session, init_db
from app.models.models import Character, CharacterState, Chapter, MemoryEntry, Project, ProjectProgress
from app.services.chapter_continuity_review_service import ChapterContinuityReviewService
from app.services.context_assembly_service import ContextAssemblyService

MCP_HTTP_SERVER_NAME = "ai-comic-mcp-http-server"
MCP_HTTP_HOST = "127.0.0.1"
MCP_HTTP_PORT = 48722

app = FastAPI(title=MCP_HTTP_SERVER_NAME)


class ToolCallRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = {}


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"name": MCP_HTTP_SERVER_NAME, "status": "online", "host": MCP_HTTP_HOST, "port": MCP_HTTP_PORT}


@app.get("/mcp/manifest")
def manifest():
    return {
        "name": MCP_HTTP_SERVER_NAME,
        "transport": "http",
        "tools": [
            tool_schema("list_projects", "列出漫画项目", {}),
            tool_schema("list_chapters", "列出项目章节", {"project_id": {"type": "string"}}, ["project_id"]),
            tool_schema(
                "get_chapter_context",
                "获取章节创作上下文 prompt",
                {"project_id": {"type": "string"}, "chapter_id": {"type": "integer"}},
                ["project_id", "chapter_id"],
            ),
            tool_schema("get_project_summary", "获取项目摘要和统计", {"project_id": {"type": "string"}}, ["project_id"]),
            tool_schema(
                "get_chapter_detail",
                "获取章节详情、版本数量、大纲和任务摘要",
                {"project_id": {"type": "string"}, "chapter_id": {"type": "integer"}},
                ["project_id", "chapter_id"],
            ),
            tool_schema(
                "list_memories",
                "按项目、章节、角色和类型查询记忆",
                {
                    "project_id": {"type": "string"},
                    "memory_type": {"type": "string"},
                    "chapter_id": {"type": "integer"},
                    "character_id": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                ["project_id"],
            ),
            tool_schema(
                "list_character_states",
                "查询角色状态",
                {
                    "project_id": {"type": "string"},
                    "chapter_id": {"type": "integer"},
                    "character_id": {"type": "integer"},
                },
                ["project_id"],
            ),
            tool_schema(
                "review_chapter_continuity",
                "审查章节正文连续性，不写入数据库",
                {"project_id": {"type": "string"}, "chapter_id": {"type": "integer"}},
                ["project_id", "chapter_id"],
            ),
        ],
    }


@app.post("/mcp/call")
def call_tool(request: ToolCallRequest, session: Session = Depends(get_session)):
    if request.name == "list_projects":
        projects = session.exec(select(Project).order_by(Project.updated_at.desc())).all()
        return {"content": [serialize_project_list_item(project) for project in projects]}

    if request.name == "list_chapters":
        project_id = require_arg(request.arguments, "project_id")
        ensure_project(session, project_id)
        chapters = session.exec(
            select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.sequence, Chapter.id)
        ).all()
        return {"content": [serialize_chapter_list_item(chapter) for chapter in chapters]}

    if request.name == "get_chapter_context":
        project_id = require_arg(request.arguments, "project_id")
        chapter_id = require_int_arg(request.arguments, "chapter_id")
        try:
            service = ContextAssemblyService(session)
            context = service.build_chapter_context(project_id, chapter_id)
            return {"content": [{"type": "text", "text": service.render_context_prompt(context)}]}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    if request.name == "get_project_summary":
        project_id = require_arg(request.arguments, "project_id")
        project = ensure_project(session, project_id)
        return {"content": get_project_summary(session, project)}

    if request.name == "get_chapter_detail":
        project_id = require_arg(request.arguments, "project_id")
        chapter_id = require_int_arg(request.arguments, "chapter_id")
        chapter = get_project_chapter(session, project_id, chapter_id)
        return {"content": get_chapter_detail(session, chapter)}

    if request.name == "list_memories":
        project_id = require_arg(request.arguments, "project_id")
        ensure_project(session, project_id)
        return {"content": list_memories(session, request.arguments)}

    if request.name == "list_character_states":
        project_id = require_arg(request.arguments, "project_id")
        ensure_project(session, project_id)
        return {"content": list_character_states(session, request.arguments)}

    if request.name == "review_chapter_continuity":
        project_id = require_arg(request.arguments, "project_id")
        chapter_id = require_int_arg(request.arguments, "chapter_id")
        chapter = get_project_chapter(session, project_id, chapter_id)
        if not (chapter.content or "").strip():
            raise HTTPException(status_code=400, detail="Chapter content is empty")
        return {"content": ChapterContinuityReviewService(session).review_chapter(chapter)}

    raise HTTPException(status_code=404, detail=f"Unknown tool: {request.name}")


def tool_schema(name: str, description: str, properties: Dict[str, Any], required: list[str] | None = None):
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return {"name": name, "description": description, "input_schema": schema}


def require_arg(arguments: Dict[str, Any], name: str):
    value = arguments.get(name)
    if value is None or value == "":
        raise HTTPException(status_code=400, detail=f"Missing argument: {name}")
    return value


def require_int_arg(arguments: Dict[str, Any], name: str) -> int:
    value = require_arg(arguments, name)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid argument: {name}")


def optional_int_arg(arguments: Dict[str, Any], name: str) -> int | None:
    value = arguments.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid argument: {name}")


def ensure_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def get_project_chapter(session: Session, project_id: str, chapter_id: int) -> Chapter:
    chapter = session.get(Chapter, chapter_id)
    if not chapter or chapter.project_id != project_id:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter


def serialize_project_list_item(project: Project):
    return {"id": project.id, "title": project.title, "description": project.description}


def serialize_chapter_list_item(chapter: Chapter):
    return {
        "id": chapter.id,
        "sequence": chapter.sequence,
        "title": chapter.title,
        "summary": chapter.summary,
        "status": chapter.status,
        "word_count": chapter.word_count,
    }


def get_project_summary(session: Session, project: Project):
    chapters = session.exec(select(Chapter).where(Chapter.project_id == project.id).order_by(Chapter.sequence, Chapter.id)).all()
    progress = session.exec(select(ProjectProgress).where(ProjectProgress.project_id == project.id)).first()
    return {
        "project": {
            "id": project.id,
            "title": project.title,
            "description": project.description,
            "theme": project.theme,
            "language": project.language,
            "workflow_mode": project.workflow_mode,
            "memory_enabled": project.memory_enabled,
            "setting_mode": project.setting_mode,
            "outline_enabled": project.outline_enabled,
            "current_chapter_id": project.current_chapter_id,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        },
        "counts": {
            "chapters": len(chapters),
            "characters": len(project.characters),
            "outlines": len(project.outlines),
            "memories": len(project.memories),
            "chapter_tasks": len(project.chapter_tasks),
        },
        "progress": serialize_progress(progress) if progress else None,
        "latest_chapter": serialize_chapter_list_item(chapters[-1]) if chapters else None,
    }


def get_chapter_detail(session: Session, chapter: Chapter):
    versions = sorted(chapter.versions, key=lambda item: (item.version_no, item.id), reverse=True)
    return {
        "chapter": {
            "id": chapter.id,
            "project_id": chapter.project_id,
            "sequence": chapter.sequence,
            "title": chapter.title,
            "summary": chapter.summary,
            "content": chapter.content,
            "preview_text": chapter.preview_text,
            "goal": chapter.goal,
            "conflict": chapter.conflict,
            "status": chapter.status,
            "current_location": chapter.current_location,
            "current_time": chapter.current_time,
            "pov_character": chapter.pov_character,
            "word_count": chapter.word_count,
            "chapter_metadata": chapter.chapter_metadata,
            "created_at": chapter.created_at,
            "updated_at": chapter.updated_at,
        },
        "versions": {"count": len(versions), "latest_version_no": versions[0].version_no if versions else None},
        "outlines": [
            {"id": outline.id, "title": outline.title, "scope": outline.scope, "content": outline.content, "sort_order": outline.sort_order}
            for outline in chapter.outlines
        ],
        "tasks": [
            {"id": task.id, "title": task.title, "status": task.status, "type": task.type, "description": task.description}
            for task in chapter.tasks
        ],
    }


def list_memories(session: Session, arguments: Dict[str, Any]):
    statement = select(MemoryEntry).where(MemoryEntry.project_id == arguments["project_id"])
    if arguments.get("memory_type"):
        statement = statement.where(MemoryEntry.memory_type == arguments["memory_type"])
    chapter_id = optional_int_arg(arguments, "chapter_id")
    character_id = optional_int_arg(arguments, "character_id")
    limit = optional_int_arg(arguments, "limit") or 50
    if chapter_id is not None:
        statement = statement.where(MemoryEntry.chapter_id == chapter_id)
    if character_id is not None:
        statement = statement.where(MemoryEntry.character_id == character_id)
    limit = min(limit, 200)
    memories = session.exec(statement.order_by(MemoryEntry.importance.desc(), MemoryEntry.updated_at.desc()).limit(limit)).all()
    return [
        {
            "id": memory.id,
            "scope": memory.scope,
            "content": memory.content,
            "memory_type": memory.memory_type,
            "chapter_id": memory.chapter_id,
            "character_id": memory.character_id,
            "tags": memory.tags,
            "importance": memory.importance,
            "source_type": memory.source_type,
            "source_id": memory.source_id,
            "is_active": memory.is_active,
            "created_at": memory.created_at,
            "updated_at": memory.updated_at,
        }
        for memory in memories
    ]


def list_character_states(session: Session, arguments: Dict[str, Any]):
    statement = select(CharacterState).where(CharacterState.project_id == arguments["project_id"])
    chapter_id = optional_int_arg(arguments, "chapter_id")
    character_id = optional_int_arg(arguments, "character_id")
    if chapter_id is not None:
        statement = statement.where(CharacterState.chapter_id == chapter_id)
    if character_id is not None:
        statement = statement.where(CharacterState.character_id == character_id)
    states = session.exec(statement.order_by(CharacterState.updated_at.desc())).all()
    return [serialize_character_state(state) for state in states]


def serialize_character_state(state: CharacterState):
    return {
        "id": state.id,
        "character_id": state.character_id,
        "character_name": state.character.name if state.character else None,
        "chapter_id": state.chapter_id,
        "physical_state": state.physical_state,
        "emotional_state": state.emotional_state,
        "location": state.location,
        "outfit_id": state.outfit_id,
        "outfit_name": state.outfit.name if state.outfit else None,
        "goal": state.goal,
        "secret": state.secret,
        "power_level": state.power_level,
        "inventory": state.inventory,
        "notes": state.notes,
        "updated_at": state.updated_at,
    }


def serialize_progress(progress: ProjectProgress):
    return {
        "current_chapter_id": progress.current_chapter_id,
        "current_arc": progress.current_arc,
        "current_location": progress.current_location,
        "current_time": progress.current_time,
        "main_conflict": progress.main_conflict,
        "active_threads": progress.active_threads,
        "resolved_threads": progress.resolved_threads,
        "pending_hooks": progress.pending_hooks,
        "notes": progress.notes,
    }
