from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.agents.base import AgentContext, AgentStep, BaseAgent
from app.models.models import Chapter, ChapterVersion
from app.services.ai_service import AIService
from app.services.chapter_state_extraction_service import extract_chapter_state_safely
from app.services.context_assembly_service import ContextAssemblyService


class ChapterAdaptationAgent(BaseAgent):
    name = "chapter_adaptation"
    label = "章节改编 Agent"
    version = "1.0"

    def steps(self) -> list[AgentStep]:
        return [
            AgentStep("load_chapter", "加载章节", 10, self._step_load_chapter),
            AgentStep("build_context", "组装章节上下文", 25, self._step_build_context),
            AgentStep("generate_content", "生成章节正文", 55, self._step_generate_content),
            AgentStep("persist_content", "保存章节正文", 80, self._step_persist_content),
            AgentStep("extract_state", "提取章节状态", 95, self._step_extract_state),
        ]

    def generate_content(self, chapter_id: int, user_input: str = "", save_version: bool = True) -> Chapter:
        chapter = self._load_chapter(chapter_id)
        context_prompt = self._build_context_prompt(chapter)
        generated_content = self._generate_content(context_prompt, user_input)
        chapter = self._persist_content(chapter, generated_content, save_version)
        self._extract_state(chapter, generated_content, context_prompt)
        self.session.refresh(chapter)
        return chapter

    def _step_load_chapter(self, context: AgentContext) -> dict[str, Any]:
        chapter_id = context.input_payload.get("chapter_id")
        chapter = self._load_chapter(chapter_id)
        context.state["_chapter"] = chapter
        return {
            "chapter_id": chapter.id,
            "project_id": chapter.project_id,
            "title": chapter.title,
        }

    def _step_build_context(self, context: AgentContext) -> dict[str, Any]:
        chapter = context.state["_chapter"]
        context_prompt = self._build_context_prompt(chapter)
        context.state["_context_prompt"] = context_prompt
        return {"context_prompt_length": len(context_prompt)}

    STREAM_UPDATE_INTERVAL_SECONDS = 1.5
    STREAM_PREVIEW_MAX_CHARS = 3000

    def _step_generate_content(self, context: AgentContext) -> dict[str, Any]:
        context_prompt = context.state["_context_prompt"]
        user_input = context.input_payload.get("user_input") or ""
        generated_content = self._generate_content(
            context_prompt, user_input, on_delta=self._make_stream_writer(context)
        )
        context.state["_generated_content"] = generated_content
        return {
            "content_length": len(generated_content or ""),
            "word_count": self._word_count(generated_content),
        }

    def _make_stream_writer(self, context: AgentContext):
        """节流地把流式生成的部分正文写入 Task，供 SSE / 前端实时展示；同时检测取消。"""
        last_flush = {"at": 0.0}

        def on_delta(full_text: str):
            now = time.monotonic()
            if now - last_flush["at"] < self.STREAM_UPDATE_INTERVAL_SECONDS:
                return
            last_flush["at"] = now

            context.raise_if_cancelled()

            task = context.task
            task.message = f"正在生成章节正文（已生成 {len(full_text)} 字）..."
            existing_result = dict(task.result or {})
            existing_result["stream_preview"] = full_text[-self.STREAM_PREVIEW_MAX_CHARS:]
            existing_result["stream_chars"] = len(full_text)
            task.result = existing_result
            task.updated_at = datetime.utcnow()
            context.session.add(task)
            context.session.commit()

        return on_delta

    def _step_persist_content(self, context: AgentContext) -> dict[str, Any]:
        chapter = context.state["_chapter"]
        generated_content = context.state["_generated_content"]
        save_version = bool(context.input_payload.get("save_version", True))
        chapter = self._persist_content(chapter, generated_content, save_version)
        context.state["_chapter"] = chapter
        result = {
            "chapter_id": chapter.id,
            "project_id": chapter.project_id,
            "preview_text": chapter.preview_text,
            "word_count": chapter.word_count,
            "version_saved": save_version,
        }
        context.result.update(result)
        return result

    def _step_extract_state(self, context: AgentContext) -> dict[str, Any]:
        chapter = context.state["_chapter"]
        generated_content = context.state["_generated_content"]
        context_prompt = context.state["_context_prompt"]
        extraction = self._extract_state(chapter, generated_content, context_prompt)
        context.result["state_extraction"] = extraction
        return extraction

    def _load_chapter(self, chapter_id: int) -> Chapter:
        chapter = self.session.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError("Chapter not found")
        return chapter

    def _build_context_prompt(self, chapter: Chapter) -> str:
        context_service = ContextAssemblyService(self.session)
        context = context_service.build_chapter_context(chapter.project_id, chapter.id)
        return context_service.render_context_prompt(context)

    def _generate_content(self, context_prompt: str, user_input: str = "", on_delta=None) -> str:
        return AIService(self.session).generate_chapter_content(context_prompt, user_input or "", on_delta=on_delta)

    def _persist_content(self, chapter: Chapter, generated_content: str, save_version: bool = True) -> Chapter:
        chapter.content = generated_content
        chapter.preview_text = generated_content[:500] if generated_content else None
        chapter.word_count = self._word_count(generated_content)
        chapter.updated_at = datetime.utcnow()
        self.session.add(chapter)
        self.session.commit()
        self.session.refresh(chapter)

        if save_version:
            version = ChapterVersion(
                project_id=chapter.project_id,
                chapter_id=chapter.id,
                title=chapter.title,
                content=generated_content,
                preview_text=chapter.preview_text,
                word_count=chapter.word_count,
                change_note="AI 生成章节正文",
                version_no=self._next_chapter_version_no(chapter.project_id, chapter.id),
            )
            self.session.add(version)
            self.session.commit()

        return chapter

    def _extract_state(self, chapter: Chapter, generated_content: str, context_prompt: str) -> dict:
        return extract_chapter_state_safely(self.session, chapter, generated_content, context_prompt)

    def _next_chapter_version_no(self, project_id: str, chapter_id: int) -> int:
        statement = (
            select(ChapterVersion)
            .where(ChapterVersion.project_id == project_id, ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.version_no.desc(), ChapterVersion.id.desc())
        )
        latest = self.session.exec(statement).first()
        return 1 if latest is None else latest.version_no + 1

    def _word_count(self, content: str | None) -> int:
        return len(content.split()) if content else 0
