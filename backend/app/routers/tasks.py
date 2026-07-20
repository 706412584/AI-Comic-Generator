import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from app.core.database import get_session
from app.models.models import AgentRun, Task
from app.schemas.schemas import AgentRunRead, TaskRead

router = APIRouter()

TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}
SUPPORTED_RETRY_TASK_TYPES = {
    "chapter_content_generation",
    "chapter_storyboard",
    "source_analysis",
}


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=_json_default)}\n\n"


def _normalize_logs(raw_logs: Any) -> list[str]:
    if raw_logs is None:
        return []
    if isinstance(raw_logs, str):
        try:
            parsed = json.loads(raw_logs)
        except json.JSONDecodeError:
            return [raw_logs] if raw_logs else []
        return _normalize_logs(parsed)
    if isinstance(raw_logs, list):
        normalized = []
        for item in raw_logs:
            if isinstance(item, str):
                normalized.append(item)
            else:
                normalized.append(json.dumps(item, ensure_ascii=False, default=_json_default))
        return normalized
    return [json.dumps(raw_logs, ensure_ascii=False, default=_json_default)]


def _task_payload(task: Task) -> dict:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "type": task.type,
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
        "name": task.name,
        "description": task.description,
        "scope_type": task.scope_type,
        "scope_id": task.scope_id,
        "input_payload": task.input_payload or {},
        "retry_count": task.retry_count,
        "retry_of_task_id": task.retry_of_task_id,
        "result": task.result or {},
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "logs": _normalize_logs(task.logs),
    }


def _state_signature(task: Task) -> dict:
    return {
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
        "updated_at": task.updated_at,
    }


@router.get("/{task_id}/events")
def stream_task_events(task_id: str, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        last_state: str | None = None
        last_log_index = 0

        while True:
            try:
                session.expire_all()
                current_task = session.get(Task, task_id)
                if not current_task:
                    yield _sse_event("error", {"detail": "Task not found"})
                    return

                state_signature = json.dumps(_state_signature(current_task), ensure_ascii=False, default=_json_default)
                if state_signature != last_state:
                    yield _sse_event("task_state", {"task": _task_payload(current_task)})
                    last_state = state_signature

                current_logs = _normalize_logs(current_task.logs)
                if len(current_logs) < last_log_index:
                    last_log_index = 0
                if len(current_logs) > last_log_index:
                    yield _sse_event("task_log", {"logs": current_logs[last_log_index:]})
                    last_log_index = len(current_logs)

                if current_task.status in TERMINAL_TASK_STATUSES:
                    yield _sse_event("done", {"task": _task_payload(current_task)})
                    return

                await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                yield _sse_event("error", {"detail": str(exc)})
                return

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{task_id}", response_model=TaskRead)
def get_task_status(task_id: str, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.get("/project/{project_id}", response_model=list[TaskRead])
def get_project_tasks(project_id: str, session: Session = Depends(get_session)):
    statement = select(Task).where(Task.project_id == project_id).order_by(Task.created_at.desc())
    tasks = session.exec(statement).all()
    # Filter only recent or active tasks if list is too long?
    # For now return all, maybe limit 20
    return tasks[:20]

@router.get("/{task_id}/agent-runs", response_model=list[AgentRunRead])
def get_task_agent_runs(task_id: str, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    statement = select(AgentRun).where(AgentRun.task_id == task_id).order_by(AgentRun.created_at.desc())
    return session.exec(statement).all()

@router.post("/{task_id}/cancel", response_model=TaskRead)
def cancel_task(task_id: str, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task.status in ["completed", "failed", "cancelled"]:
        return task
        
    task.status = "cancelled"
    task.message = "Task cancelled by user"
    session.add(task)
    session.commit()
    session.refresh(task)
    return task

@router.post("/{task_id}/retry", response_model=TaskRead)
def retry_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "failed":
        raise HTTPException(status_code=400, detail="Only failed tasks can be retried")
    if task.type not in SUPPORTED_RETRY_TASK_TYPES:
        raise HTTPException(status_code=400, detail="Task type does not support retry")
    if not task.input_payload:
        raise HTTPException(status_code=400, detail="Task input payload is required for retry")

    retry = Task(
        project_id=task.project_id,
        type=task.type,
        status="pending",
        progress=0,
        name=task.name,
        description=task.description,
        scope_type=task.scope_type,
        scope_id=task.scope_id,
        input_payload=dict(task.input_payload or {}),
        retry_count=(task.retry_count or 0) + 1,
        retry_of_task_id=task.id,
        message="等待重试任务执行...",
    )
    session.add(retry)
    session.commit()
    session.refresh(retry)

    payload = retry.input_payload or {}
    try:
        if retry.type == "chapter_content_generation":
            chapter_id = payload.get("chapter_id")
            if chapter_id is None:
                raise ValueError("chapter_id is required")
            from app.routers.generation import generate_chapter_content_task

            background_tasks.add_task(
                generate_chapter_content_task,
                retry.id,
                int(chapter_id),
                payload.get("user_input") or "",
                bool(payload.get("save_version", True)),
            )
        elif retry.type == "chapter_storyboard":
            chapter_id = payload.get("chapter_id")
            if chapter_id is None:
                raise ValueError("chapter_id is required")
            from app.routers.generation import generate_chapter_storyboard_task

            background_tasks.add_task(
                generate_chapter_storyboard_task,
                retry.id,
                int(chapter_id),
                payload.get("user_input") or "",
            )
        elif retry.type == "source_analysis":
            from app.routers.generation import generate_source_analysis_task

            background_tasks.add_task(
                generate_source_analysis_task,
                retry.id,
                retry.project_id,
                payload.get("max_chapters", 50),
                payload.get("mode", "continue"),
            )
        else:
            raise ValueError("Task type does not support retry")
    except ValueError as exc:
        session.delete(retry)
        session.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return retry
