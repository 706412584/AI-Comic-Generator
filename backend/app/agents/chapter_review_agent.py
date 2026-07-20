from __future__ import annotations

from app.agents.base import BaseAgent
from app.models.models import Chapter
from app.services.chapter_continuity_review_service import ChapterContinuityReviewService


class ChapterReviewAgent(BaseAgent):
    name = "chapter_review"
    label = "章节审查 Agent"
    version = "1.0"

    def review_continuity(self, chapter_id: int) -> dict:
        chapter = self.session.get(Chapter, chapter_id)
        if not chapter:
            raise ValueError("Chapter not found")
        if not (chapter.content or "").strip():
            raise ValueError("Chapter content is empty")
        return ChapterContinuityReviewService(self.session).review_chapter(chapter)
