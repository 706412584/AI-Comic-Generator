from __future__ import annotations

from datetime import datetime
from typing import Any
import json

from sqlmodel import Session

from app.agents.base import AgentContext, BaseAgent
from app.models.models import AgentRun, Task


class AgentRuntime:
    def __init__(self, session: Session, task_id: str, agent: BaseAgent, input_payload: dict[str, Any] | None = None):
        self.session = session
        self.task_id = task_id
        self.agent = agent
        self.input_payload = input_payload or {}

    def run(self) -> dict[str, Any]:
        task = self.session.get(Task, self.task_id)
        if not task:
            raise ValueError("Task not found")

        steps = self.agent.steps()
        agent_run = AgentRun(
            task_id=task.id,
            project_id=task.project_id,
            chapter_id=self.input_payload.get("chapter_id"),
            agent_name=self.agent.name,
            agent_version=self.agent.version,
            status="processing",
            total_steps=len(steps),
            input_payload=self.input_payload,
            started_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.session.add(agent_run)
        self._update_task(task, "processing", 1, f"{self.agent.label} 开始执行")
        self.session.commit()
        self.session.refresh(agent_run)

        context = AgentContext(
            session=self.session,
            task=task,
            agent_run=agent_run,
            input_payload=self.input_payload,
            state={},
            result={},
        )

        try:
            for index, step in enumerate(steps, start=1):
                self.session.refresh(task)
                if task.status == "cancelled":
                    agent_run.status = "cancelled"
                    agent_run.current_step = step.name
                    agent_run.step_index = index - 1
                    agent_run.updated_at = datetime.utcnow()
                    agent_run.finished_at = datetime.utcnow()
                    self.session.add(agent_run)
                    self.session.commit()
                    return {"agent_name": self.agent.name, "status": "cancelled"}

                agent_run.current_step = step.name
                agent_run.step_index = index
                agent_run.updated_at = datetime.utcnow()
                self._update_task(task, "processing", step.progress, f"{step.label}...")
                self.session.add(agent_run)
                self.session.commit()

                step_result = step.handler(context) or {}
                if step_result:
                    context.state[step.name] = step_result
                    agent_run.state_payload = self._json_safe(context.state)
                    self.session.add(agent_run)
                    self.session.commit()

            agent_run.status = "completed"
            agent_run.current_step = None
            agent_run.result_payload = self._json_safe(context.result or context.state)
            agent_run.updated_at = datetime.utcnow()
            agent_run.finished_at = datetime.utcnow()
            self.session.add(agent_run)
            self.session.commit()
            return {
                "agent_name": self.agent.name,
                "agent_label": self.agent.label,
                "agent_run_id": agent_run.id,
                "completed_steps": [step.name for step in steps],
                "summary": context.result or context.state,
            }
        except Exception as exc:
            agent_run.status = "failed"
            agent_run.error_payload = {
                "step": agent_run.current_step,
                "error": str(exc),
            }
            agent_run.updated_at = datetime.utcnow()
            agent_run.finished_at = datetime.utcnow()
            self.session.add(agent_run)
            self.session.commit()
            raise

    def _json_safe(self, value: Any):
        try:
            json.dumps(value, ensure_ascii=False)
            return value
        except TypeError:
            if isinstance(value, dict):
                return {key: self._json_safe(item) for key, item in value.items() if not key.startswith("_")}
            if isinstance(value, (list, tuple)):
                return [self._json_safe(item) for item in value]
            if hasattr(value, "model_dump"):
                data = value.model_dump()
                return {key: self._json_safe(item) for key, item in data.items()}
            return str(value)

    def _update_task(self, task: Task, status: str, progress: int, message: str):
        task.status = status
        task.progress = progress
        task.message = message
        task.updated_at = datetime.utcnow()
        logs = list(task.logs) if task.logs else []
        logs.append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] [{self.agent.name}] {message}")
        task.logs = logs
        self.session.add(task)
