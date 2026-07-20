from __future__ import annotations

from app.agents.base import AgentContext, AgentStep, BaseAgent
from app.models.models import Task
from app.routers.generation import (
    AIService,
    build_source_initialization_context,
    build_source_initialization_step_prompt,
    get_source_chapters_for_import,
    has_initialized_content,
    latest_source_import,
    parse_ai_json_object,
    persist_project_initialization_payload,
)


class SourceProjectInitAgent(BaseAgent):
    name = "source_project_init"
    label = "原文项目初始化 Agent"
    version = "1.0"

    def steps(self) -> list[AgentStep]:
        return [
            AgentStep("load_source_context", "加载原文摘要上下文", 10, self.load_source_context),
            AgentStep("generate_project_settings", "AI 正在生成项目基础信息和世界观设定", 20, self.generate_project_settings),
            AgentStep("generate_characters_relationships", "AI 正在生成角色和人物关系", 35, self.generate_characters_relationships),
            AgentStep("generate_outlines_chapters", "AI 正在生成大纲和章节规划", 50, self.generate_outlines_chapters),
            AgentStep("generate_memories_progress", "AI 正在生成初始记忆和进度状态", 65, self.generate_memories_progress),
            AgentStep("persist_payload", "正在写入设定、角色、关系和章节", 80, self.persist_payload),
        ]

    def load_source_context(self, context: AgentContext) -> dict:
        project_id = context.input_payload["project_id"]
        if has_initialized_content(context.session, project_id):
            raise ValueError("项目已有设定、角色、章节或大纲，请在空项目中使用原文初始化")

        source_import = latest_source_import(context.session, project_id)
        summary_layers = source_import.summary_layers if isinstance(source_import.summary_layers, dict) else {}
        has_layered_context = bool(summary_layers.get("chunks"))
        source_chapters = get_source_chapters_for_import(context.session, source_import.id, limit=None if has_layered_context else 120)
        if not source_chapters:
            raise ValueError("未找到原文章节")

        context.state["project_id"] = project_id
        context.state["_source_import"] = source_import
        context.state["_source_chapters"] = source_chapters
        context.state["source_context"] = build_source_initialization_context(source_import, source_chapters)
        context.result["source_import_id"] = source_import.id
        return {"source_import_id": source_import.id, "source_chapter_count": len(source_chapters), "layered_context": has_layered_context}

    def generate_project_settings(self, context: AgentContext) -> dict:
        payload = context.state.setdefault("payload", {})
        result = self._generate_step(context, "project_settings", payload, "project")
        payload.update(result)
        return {"project": bool(payload.get("project")), "settings": len(payload.get("settings") or [])}

    def generate_characters_relationships(self, context: AgentContext) -> dict:
        payload = context.state.setdefault("payload", {})
        result = self._generate_step(context, "characters_relationships", payload, "characters")
        payload.update(result)
        return {"characters": len(payload.get("characters") or []), "relationships": len(payload.get("relationships") or [])}

    def generate_outlines_chapters(self, context: AgentContext) -> dict:
        payload = context.state.setdefault("payload", {})
        result = self._generate_step(context, "outlines_chapters", payload, "chapters")
        payload.update(result)
        return {"outlines": len(payload.get("outlines") or []), "chapters": len(payload.get("chapters") or [])}

    def generate_memories_progress(self, context: AgentContext) -> dict:
        payload = context.state.setdefault("payload", {})
        result = self._generate_step(context, "memories_progress", payload, "progress")
        payload.update(result)
        return {"memories": len(payload.get("memories") or []), "progress": bool(payload.get("progress"))}

    def persist_payload(self, context: AgentContext) -> dict:
        project_id = context.state["project_id"]
        source_import = context.state["_source_import"]
        source_chapters = context.state["_source_chapters"]
        payload = context.state["payload"]
        result = persist_project_initialization_payload(
            context.session,
            project_id,
            payload,
            story_input=source_import.raw_text,
            task_id=context.task.id,
            source_chapters=source_chapters,
        )
        context.session.commit()
        result["source_import_id"] = source_import.id
        context.result.update(result)
        return result

    def _generate_step(self, context: AgentContext, step: str, payload: dict, required_key: str) -> dict:
        system_prompt, prompt = build_source_initialization_step_prompt(context.state["source_context"], step, payload)
        generated = AIService(context.session).generate_text(system_prompt, prompt)
        return parse_ai_json_object(generated, required_key=required_key)
