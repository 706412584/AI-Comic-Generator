from __future__ import annotations

from datetime import datetime

from app.agents.base import AgentContext, AgentStep, BaseAgent
from app.models.models import Task
from app.routers.generation import (
    AIService,
    build_source_chapter_summary_prompt,
    build_source_chunk_summary_prompt,
    build_source_import_summary_prompt,
    build_source_layered_book_summary_prompt,
    get_source_chapters_for_import,
    latest_source_import,
    normalize_list,
    parse_ai_json_object,
)


MODEL_CONFIG_ERROR_MARKERS = (
    "No active configuration found",
    "active configuration",
    "模型配置",
)

LAYERED_SUMMARY_THRESHOLD = 120
SOURCE_SUMMARY_CHUNK_SIZE = 30


class SourceAnalysisAgent(BaseAgent):
    name = "source_analysis"
    label = "原文分析 Agent"
    version = "1.0"

    def steps(self) -> list[AgentStep]:
        return [
            AgentStep("load_source_import", "准备分析小说原文", 10, self.load_source_import),
            AgentStep("select_chapters", "选择待分析原文章节", 18, self.select_chapters),
            AgentStep("analyze_chapters", "AI 正在分析原文章节", 30, self.analyze_chapters),
            AgentStep("summarize_book", "正在汇总整本小说摘要", 82, self.summarize_book),
            AgentStep("finalize_import_status", "正在更新原文分析状态", 95, self.finalize_import_status),
        ]

    def load_source_import(self, context: AgentContext) -> dict:
        project_id = context.input_payload["project_id"]
        source_import = latest_source_import(context.session, project_id)
        all_chapters = get_source_chapters_for_import(context.session, source_import.id)
        if not all_chapters:
            raise ValueError("未找到原文章节")

        context.state["project_id"] = project_id
        context.state["mode"] = context.input_payload.get("mode") or "continue"
        context.state["max_chapters"] = context.input_payload.get("max_chapters")
        context.state["_source_import"] = source_import
        context.state["_all_chapters"] = all_chapters
        context.result["source_import_id"] = source_import.id
        return {"source_import_id": source_import.id, "total_chapters": len(all_chapters)}

    def select_chapters(self, context: AgentContext) -> dict:
        mode = context.state.get("mode") or "continue"
        max_chapters = context.state.get("max_chapters")
        all_chapters = context.state["_all_chapters"]

        if mode in ("restart", "all"):
            candidate_chapters = all_chapters
        else:
            candidate_chapters = [
                chapter for chapter in all_chapters
                if chapter.analysis_status in ("pending", "failed") or not (chapter.summary_short or "").strip()
            ]

        chapters_to_analyze = candidate_chapters[:max_chapters] if max_chapters else candidate_chapters
        context.state["_chapters_to_analyze"] = chapters_to_analyze
        context.state["selected_chapter_ids"] = [chapter.id for chapter in chapters_to_analyze]
        return {
            "mode": mode,
            "max_chapters": max_chapters,
            "candidate_chapters": len(candidate_chapters),
            "selected_chapters": len(chapters_to_analyze),
        }

    def analyze_chapters(self, context: AgentContext) -> dict:
        chapters_to_analyze = context.state.get("_chapters_to_analyze") or []
        context.state["failed_chapters"] = []
        context.state["analyzed_this_run"] = 0
        if not chapters_to_analyze:
            return {"analyzed_this_run": 0, "failed_count": 0, "failed_chapters": []}

        ai = AIService(context.session)
        for index, source_chapter in enumerate(chapters_to_analyze, start=1):
            progress = 10 + int(index / max(len(chapters_to_analyze), 1) * 65)
            self._update_task_progress(
                context,
                progress,
                f"正在分析原文章节 {index}/{len(chapters_to_analyze)}：{source_chapter.title}",
            )
            try:
                system_prompt, prompt = build_source_chapter_summary_prompt(source_chapter)
                payload = parse_ai_json_object(ai.generate_text(system_prompt, prompt))
            except Exception as exc:
                if self._is_model_config_error(exc):
                    raise
                error_message = str(exc)
                source_chapter.analysis_status = "failed"
                source_chapter.analysis_error = error_message
                source_chapter.analysis_attempts = (source_chapter.analysis_attempts or 0) + 1
                source_chapter.updated_at = datetime.utcnow()
                context.session.add(source_chapter)
                context.session.commit()
                context.state["failed_chapters"].append({
                    "id": source_chapter.id,
                    "sequence": source_chapter.sequence,
                    "title": source_chapter.title,
                    "error": error_message,
                })
                continue

            source_chapter.summary_short = str(payload.get("summary_short") or "")
            source_chapter.summary_medium = str(payload.get("summary_medium") or source_chapter.summary_short or "")
            source_chapter.key_characters = normalize_list(payload.get("key_characters"))
            source_chapter.key_locations = normalize_list(payload.get("key_locations"))
            source_chapter.key_events = normalize_list(payload.get("key_events"))
            source_chapter.time_markers = normalize_list(payload.get("time_markers"))
            source_chapter.analysis_status = "analyzed"
            source_chapter.analysis_error = None
            source_chapter.analysis_attempts = (source_chapter.analysis_attempts or 0) + 1
            source_chapter.updated_at = datetime.utcnow()
            context.session.add(source_chapter)
            context.session.commit()
            context.state["analyzed_this_run"] += 1

        analyzed_this_run = context.state["analyzed_this_run"]
        failed_chapters = context.state["failed_chapters"]
        if failed_chapters and analyzed_this_run == 0:
            raise RuntimeError(f"本轮原文章节分析全部失败（{len(failed_chapters)} 章）")

        return {
            "analyzed_this_run": analyzed_this_run,
            "failed_count": len(failed_chapters),
            "failed_chapters": failed_chapters,
        }

    def summarize_book(self, context: AgentContext) -> dict:
        source_import = context.state["_source_import"]
        chapters_to_analyze = context.state.get("_chapters_to_analyze") or []
        if not chapters_to_analyze or context.state.get("analyzed_this_run", 0) == 0:
            return {"skipped": True}

        analyzed_chapters = [
            chapter for chapter in get_source_chapters_for_import(context.session, source_import.id)
            if chapter.analysis_status == "analyzed" or (chapter.summary_short or "").strip()
        ]
        if len(analyzed_chapters) > LAYERED_SUMMARY_THRESHOLD:
            return self._summarize_book_layered(context, source_import, analyzed_chapters)

        self._update_task_progress(context, 82, "正在汇总整本小说摘要...")
        refreshed = analyzed_chapters[:120]
        system_prompt, prompt = build_source_import_summary_prompt(source_import, refreshed)
        payload = parse_ai_json_object(AIService(context.session).generate_text(system_prompt, prompt))
        source_import.book_summary = str(payload.get("book_summary") or "")
        source_import.world_summary = str(payload.get("world_summary") or "")
        source_import.character_summary = str(payload.get("character_summary") or "")
        source_import.outline_summary = str(payload.get("outline_summary") or "")
        source_import.summary_layers = {}
        source_import.updated_at = datetime.utcnow()
        context.session.add(source_import)
        context.session.commit()
        return {
            "book_summary": bool(source_import.book_summary),
            "world_summary": bool(source_import.world_summary),
            "character_summary": bool(source_import.character_summary),
            "outline_summary": bool(source_import.outline_summary),
            "layered_summary": False,
            "chunk_count": 0,
        }

    def _summarize_book_layered(self, context: AgentContext, source_import, analyzed_chapters: list) -> dict:
        self._update_task_progress(context, 82, "正在生成长篇小说分层摘要...")
        ai = AIService(context.session)
        chunks = []
        chapter_groups = [
            analyzed_chapters[index:index + SOURCE_SUMMARY_CHUNK_SIZE]
            for index in range(0, len(analyzed_chapters), SOURCE_SUMMARY_CHUNK_SIZE)
        ]
        for index, chapters_chunk in enumerate(chapter_groups, start=1):
            self._update_task_progress(context, 82, f"正在生成分组摘要 {index}/{len(chapter_groups)}...")
            system_prompt, prompt = build_source_chunk_summary_prompt(source_import, chapters_chunk)
            payload = parse_ai_json_object(ai.generate_text(system_prompt, prompt))
            chunk_summary = {
                "index": index,
                "start_sequence": chapters_chunk[0].sequence,
                "end_sequence": chapters_chunk[-1].sequence,
                "chapter_count": len(chapters_chunk),
                "title": str(payload.get("title") or f"第 {chapters_chunk[0].sequence}-{chapters_chunk[-1].sequence} 章"),
                "summary": str(payload.get("summary") or ""),
                "key_characters": normalize_list(payload.get("key_characters")),
                "key_events": normalize_list(payload.get("key_events")),
                "key_locations": normalize_list(payload.get("key_locations")),
            }
            chunks.append(chunk_summary)

        self._update_task_progress(context, 88, "正在基于分组摘要生成全书总纲...")
        system_prompt, prompt = build_source_layered_book_summary_prompt(source_import, chunks)
        book_payload = parse_ai_json_object(ai.generate_text(system_prompt, prompt))
        source_import.book_summary = str(book_payload.get("book_summary") or "")
        source_import.world_summary = str(book_payload.get("world_summary") or "")
        source_import.character_summary = str(book_payload.get("character_summary") or "")
        source_import.outline_summary = str(book_payload.get("outline_summary") or "")
        source_import.summary_layers = {
            "chunk_size": SOURCE_SUMMARY_CHUNK_SIZE,
            "threshold": LAYERED_SUMMARY_THRESHOLD,
            "chunks": chunks,
            "book": {
                "book_summary": source_import.book_summary,
                "world_summary": source_import.world_summary,
                "character_summary": source_import.character_summary,
                "outline_summary": source_import.outline_summary,
            },
            "generated_at": datetime.utcnow().isoformat(),
            "analyzed_chapter_count": len(analyzed_chapters),
        }
        source_import.updated_at = datetime.utcnow()
        context.session.add(source_import)
        context.session.commit()
        context.result.update({"layered_summary": True, "chunk_count": len(chunks)})
        return {
            "book_summary": bool(source_import.book_summary),
            "world_summary": bool(source_import.world_summary),
            "character_summary": bool(source_import.character_summary),
            "outline_summary": bool(source_import.outline_summary),
            "layered_summary": True,
            "chunk_count": len(chunks),
        }

    def finalize_import_status(self, context: AgentContext) -> dict:
        source_import = context.state["_source_import"]
        all_after = get_source_chapters_for_import(context.session, source_import.id)
        analyzed_count = sum(1 for chapter in all_after if chapter.analysis_status == "analyzed" or (chapter.summary_short or "").strip())
        failed_chapters = context.state.get("failed_chapters") or []
        failed_count = len(failed_chapters)
        analyzed_this_run = context.state.get("analyzed_this_run", 0)
        total_count = len(all_after)
        is_partial = analyzed_count < total_count
        source_import.import_status = "analyzed_with_errors" if failed_count else ("partially_analyzed" if is_partial else "analyzed")
        source_import.updated_at = datetime.utcnow()
        context.session.add(source_import)
        context.session.commit()

        result = {
            "source_import_id": source_import.id,
            "failed_chapters": failed_chapters,
            "failed_count": failed_count,
            "analyzed_this_run": analyzed_this_run,
            "total_chapters": total_count,
            "analyzed_chapters": analyzed_count,
            "partial": is_partial or failed_count > 0,
        }
        context.result.update(result)
        return result

    def _is_model_config_error(self, exc: Exception) -> bool:
        message = str(exc)
        return any(marker in message for marker in MODEL_CONFIG_ERROR_MARKERS)

    def _update_task_progress(self, context: AgentContext, progress: int, message: str):
        task: Task = context.task
        task.progress = progress
        task.message = message
        task.updated_at = datetime.utcnow()
        current_logs = list(task.logs) if task.logs else []
        current_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        task.logs = current_logs
        context.session.add(task)
        context.session.commit()
