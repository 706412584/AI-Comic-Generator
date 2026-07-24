from __future__ import annotations

import time
from datetime import datetime

from app.agents.base import AgentContext, AgentStep, BaseAgent
from app.routers.generation import (
    AIService,
    build_project_initialization_prompt,
    has_initialized_content,
    parse_ai_json_object,
    persist_project_initialization_payload,
)


class ProjectInitializationAgent(BaseAgent):
    name = "project_initialization"
    label = "一句话项目初始化 Agent"
    version = "1.0"

    STREAM_UPDATE_INTERVAL_SECONDS = 1.0
    STREAM_PREVIEW_MAX_CHARS = 3000

    def steps(self) -> list[AgentStep]:
        return [
            AgentStep("validate_project", "检查项目初始化条件", 5, self.validate_project),
            AgentStep("generate_skeleton", "AI 正在理解一句话创意并生成项目骨架", 10, self.generate_skeleton),
            AgentStep("persist_skeleton", "正在写入设定、角色、关系、大纲和章节", 85, self.persist_skeleton),
        ]

    def validate_project(self, context: AgentContext) -> dict:
        project_id = context.input_payload["project_id"]
        if has_initialized_content(context.session, project_id):
            raise ValueError("项目已有设定、角色、章节或大纲，请在空项目中使用一句话初始化")
        context.state["project_id"] = project_id
        return {"project_id": project_id}

    def generate_skeleton(self, context: AgentContext) -> dict:
        user_input = context.input_payload.get("user_input") or ""
        system_prompt, prompt = build_project_initialization_prompt(user_input)
        stream_writer = self._make_stream_writer(context)
        generated = AIService(context.session).generate_text_stream(system_prompt, prompt, stream_writer)
        stream_writer(generated, force=True)
        self._payload = parse_ai_json_object(generated, required_key="project")
        return {"received_chars": len(generated)}

    def persist_skeleton(self, context: AgentContext) -> dict:
        project_id = context.state["project_id"]
        if has_initialized_content(context.session, project_id):
            raise ValueError("项目已完成初始化，取消重复写入")
        result = persist_project_initialization_payload(
            context.session,
            project_id,
            self._payload,
            story_input=context.input_payload.get("user_input") or "",
            task_id=context.task.id,
        )
        context.session.commit()
        context.result.update(result)
        return result

    def _make_stream_writer(self, context: AgentContext):
        last_flush = {"at": 0.0}

        def on_delta(full_text: str, force: bool = False):
            now = time.monotonic()
            if not force and now - last_flush["at"] < self.STREAM_UPDATE_INTERVAL_SECONDS:
                return
            last_flush["at"] = now
            context.raise_if_cancelled()

            task = context.task
            task.message = f"AI 正在生成项目骨架（已接收 {len(full_text)} 字）..."
            result = dict(task.result or {})
            preview = full_text[-self.STREAM_PREVIEW_MAX_CHARS:]
            result["stream_preview"] = preview
            result["stream_chars"] = len(full_text)
            task.result = result
            task.updated_at = datetime.utcnow()
            stream_state = {
                "received_chars": len(full_text),
                "preview": preview,
            }
            context.state["generate_skeleton_stream"] = stream_state
            context.agent_run.state_payload = {
                **dict(context.agent_run.state_payload or {}),
                "generate_skeleton_stream": stream_state,
            }
            context.agent_run.updated_at = datetime.utcnow()
            context.session.add(task)
            context.session.add(context.agent_run)
            context.session.commit()

        return on_delta
