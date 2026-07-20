from typing import Any

from sqlmodel import Session

from app.models.models import Chapter
from app.services.ai_service import AIService
from app.services.context_assembly_service import ContextAssemblyService
from app.utils.json_utils import extract_json_blocks


class ChapterContinuityReviewService:
    def __init__(self, session: Session):
        self.session = session

    def review_chapter(self, chapter: Chapter) -> dict:
        context_service = ContextAssemblyService(self.session)
        context = context_service.build_chapter_context(chapter.project_id, chapter.id)
        context_prompt = context_service.render_context_prompt(context)
        content = chapter.content or ""

        system_prompt = "你是长篇小说/漫画连续性审查助手。只输出 JSON，不要输出解释。"
        user_input = f"""
请审查当前章节正文是否与项目设定、人物关系、角色状态、进度和记忆冲突。

【项目上下文】
{context_prompt[:6000]}

【当前章节正文】
{content[:10000] if content else '暂无正文'}

请输出 JSON 对象：
{{
  "summary": "总体审查结论",
  "issues": [
    {{
      "severity": "low|medium|high",
      "category": "setting|character_state|relationship|timeline|memory|plot",
      "message": "问题说明",
      "evidence": "正文或上下文证据",
      "suggestion": "修改建议"
    }}
  ]
}}
如果没有问题，issues 输出空数组。
""".strip()

        generated = AIService(self.session).generate_text(system_prompt, user_input)
        blocks = extract_json_blocks(generated)
        payload = next((block for block in blocks if isinstance(block, dict)), None)
        if not payload:
            return {
                "chapter_id": chapter.id,
                "summary": "未能解析连续性审查结果。",
                "issues": [],
                "raw_output": generated,
            }

        issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
        return {
            "chapter_id": chapter.id,
            "summary": str(payload.get("summary") or "连续性审查完成。"),
            "issues": [self._normalize_issue(issue) for issue in issues if isinstance(issue, dict)],
        }

    def _normalize_issue(self, issue: dict[str, Any]) -> dict:
        severity = str(issue.get("severity") or "medium")
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        return {
            "severity": severity,
            "category": str(issue.get("category") or "plot"),
            "message": str(issue.get("message") or "未提供问题说明"),
            "evidence": str(issue.get("evidence") or ""),
            "suggestion": str(issue.get("suggestion") or ""),
        }
