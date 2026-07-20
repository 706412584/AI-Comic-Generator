"""统一的后台任务分发与重启恢复。

数据库中的 Task 表即持久化队列：所有任务创建时写入 input_payload，
执行统一通过 run_task 路由到对应的 runner。服务重启后，
recover_interrupted_tasks 会把中断的任务重新排队执行（无法恢复的标记失败）。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from sqlmodel import Session, select

logger = logging.getLogger(__name__)

# 可以从 input_payload 完整重建执行参数的任务类型
RECOVERABLE_TASK_TYPES = {
    "project_initialization",
    "source_analysis",
    "source_project_initialization",
    "chapter_content_generation",
    "chapter_storyboard",
    "storyboard",
    "image_generation",
    "character_generation",
}


def run_task(task_id: str, task_type: str, payload: dict | None = None):
    """按类型把任务路由到对应 runner。runner 自建 Session，可在任意线程执行。"""
    from app.routers import generation as g

    payload = payload or {}

    if task_type == "project_initialization":
        g.generate_project_initialization_task(task_id, payload["project_id"], payload.get("user_input") or "")
    elif task_type == "source_analysis":
        g.generate_source_analysis_task(
            task_id,
            payload["project_id"],
            payload.get("max_chapters", 50),
            payload.get("mode", "continue"),
        )
    elif task_type == "source_project_initialization":
        g.generate_source_project_initialization_task(task_id, payload["project_id"])
    elif task_type == "chapter_content_generation":
        g.generate_chapter_content_task(
            task_id,
            int(payload["chapter_id"]),
            payload.get("user_input") or "",
            bool(payload.get("save_version", True)),
        )
    elif task_type == "chapter_storyboard":
        g.generate_chapter_storyboard_task(task_id, int(payload["chapter_id"]), payload.get("user_input") or "")
    elif task_type == "storyboard":
        g.generate_storyboard_task(task_id, payload["project_id"], payload.get("user_input") or "")
    elif task_type == "image_generation":
        if payload.get("item_id") is not None:
            g.generate_panel_task(task_id, int(payload["item_id"]))
        else:
            g.generate_all_images_task(task_id, payload["project_id"])
    elif task_type == "character_generation":
        if payload.get("character_id") is not None:
            g.generate_character_task(task_id, int(payload["character_id"]))
        else:
            g.generate_all_characters_task(task_id, payload["project_id"])
    else:
        raise ValueError(f"Unknown task type: {task_type}")


def _can_recover(task) -> bool:
    return task.type in RECOVERABLE_TASK_TYPES and bool(task.input_payload)


def recover_interrupted_tasks():
    """服务启动时调用：重新排队可恢复的中断任务，其余标记失败。"""
    from app.core.database import engine
    from app.models.models import Task

    to_rerun: list[tuple[str, str, dict]] = []
    with Session(engine) as session:
        interrupted = session.exec(
            select(Task).where(Task.status.in_(["pending", "processing"]))
        ).all()

        for task in interrupted:
            logs = list(task.logs) if task.logs else []
            if _can_recover(task):
                task.status = "pending"
                task.message = "服务重启，任务已重新排队执行"
                logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 检测到服务重启，任务重新排队")
                to_rerun.append((task.id, task.type, dict(task.input_payload or {})))
            else:
                task.status = "failed"
                task.message = "服务重启导致任务中断，无法自动恢复，请重新发起"
                logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 服务重启导致任务中断")
            task.logs = logs
            task.updated_at = datetime.utcnow()
            session.add(task)
        session.commit()

    if not to_rerun:
        return

    logger.info(f"Recovering {len(to_rerun)} interrupted task(s) after restart")

    def _worker():
        # 顺序执行恢复任务，避免重启后瞬间并发打爆 AI 服务
        for task_id, task_type, payload in to_rerun:
            try:
                run_task(task_id, task_type, payload)
            except Exception as exc:
                logger.error(f"Recovered task {task_id} ({task_type}) failed: {exc}")

    threading.Thread(target=_worker, name="task-recovery", daemon=True).start()
