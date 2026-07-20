import logging
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.models.models import Character, CharacterState, Chapter, MemoryEntry, ProjectProgress
from app.services.ai_service import AIService
from app.utils.json_utils import extract_json_blocks

logger = logging.getLogger(__name__)


class ChapterStateExtractionService:
    def __init__(self, session: Session):
        self.session = session

    def extract_and_save(self, chapter: Chapter, content: str, context_prompt: str = "") -> dict:
        if not content:
            return {"memories": 0, "character_states": 0, "progress_updated": False}

        characters = self.session.exec(
            select(Character).where(Character.project_id == chapter.project_id)
        ).all()
        character_lines = [f"- id={character.id}, name={character.name}" for character in characters]
        character_map = {character.name: character for character in characters}

        system_prompt = "你是小说连续性整理助手。只输出 JSON，不要输出解释。"
        user_input = f"""
请从章节正文中抽取可用于后续创作的连续性状态。

【可用角色】
{chr(10).join(character_lines) if character_lines else '无'}

【上下文摘要】
{context_prompt[:4000]}

【章节正文】
{content[:8000]}

输出一个 JSON 对象，格式如下：
{{
  "memories": [
    {{"content": "关键事实", "memory_type": "event|trait|world|foreshadow", "character_name": "角色名或空", "tags": ["标签"], "importance": 1-5}}
  ],
  "character_states": [
    {{"character_name": "角色名", "physical_state": "身体状态", "emotional_state": "情绪状态", "location": "位置", "goal": "当前目标", "power_level": "能力状态", "inventory": ["物品"], "notes": "补充"}}
  ],
  "progress": {{
    "current_arc": "当前篇章/阶段",
    "current_location": "当前位置",
    "current_time": "当前时间",
    "main_conflict": "主要冲突",
    "active_threads": ["未解决线索"],
    "resolved_threads": ["已解决线索"],
    "pending_hooks": ["伏笔/钩子"],
    "notes": "进度备注"
  }}
}}
""".strip()

        generated = AIService(self.session).generate_text(system_prompt, user_input)
        blocks = extract_json_blocks(generated)
        payload = next((block for block in blocks if isinstance(block, dict)), {})
        if not payload:
            return {"memories": 0, "character_states": 0, "progress_updated": False}

        memories_count = self._save_memories(chapter, payload.get("memories") or [], character_map)
        states_count = self._save_character_states(chapter, payload.get("character_states") or [], character_map)
        progress_updated = self._save_progress(chapter, payload.get("progress") or {})
        self.session.commit()

        return {
            "memories": memories_count,
            "character_states": states_count,
            "progress_updated": progress_updated,
        }

    def _save_memories(self, chapter: Chapter, memories: list[Any], character_map: dict[str, Character]) -> int:
        count = 0
        for item in memories:
            if not isinstance(item, dict) or not item.get("content"):
                continue
            character = self._match_character(item.get("character_name"), character_map)
            memory = MemoryEntry(
                project_id=chapter.project_id,
                scope="chapter",
                content=str(item["content"]),
                memory_type=str(item.get("memory_type") or "event"),
                chapter_id=chapter.id,
                character_id=character.id if character else None,
                tags=item.get("tags") if isinstance(item.get("tags"), list) else [],
                importance=self._bounded_importance(item.get("importance")),
                source_type="chapter_content",
                source_id=str(chapter.id),
            )
            self.session.add(memory)
            count += 1
        return count

    def _save_character_states(self, chapter: Chapter, states: list[Any], character_map: dict[str, Character]) -> int:
        count = 0
        for item in states:
            if not isinstance(item, dict):
                continue
            character = self._match_character(item.get("character_name"), character_map)
            if not character:
                continue

            statement = select(CharacterState).where(
                CharacterState.project_id == chapter.project_id,
                CharacterState.chapter_id == chapter.id,
                CharacterState.character_id == character.id,
            )
            state = self.session.exec(statement).first()
            if not state:
                state = CharacterState(project_id=chapter.project_id, chapter_id=chapter.id, character_id=character.id)

            for field in ["physical_state", "emotional_state", "location", "goal", "power_level", "notes"]:
                if item.get(field) is not None:
                    setattr(state, field, item.get(field))
            if isinstance(item.get("inventory"), list):
                state.inventory = item["inventory"]
            state.updated_at = datetime.utcnow()
            self.session.add(state)
            count += 1
        return count

    def _save_progress(self, chapter: Chapter, progress_data: dict[str, Any]) -> bool:
        if not isinstance(progress_data, dict) or not progress_data:
            return False

        progress = self.session.exec(
            select(ProjectProgress).where(ProjectProgress.project_id == chapter.project_id)
        ).first()
        if not progress:
            progress = ProjectProgress(project_id=chapter.project_id)

        progress.current_chapter_id = chapter.id
        for field in ["current_arc", "current_location", "current_time", "main_conflict", "notes"]:
            if progress_data.get(field) is not None:
                setattr(progress, field, progress_data.get(field))
        for field in ["active_threads", "resolved_threads", "pending_hooks"]:
            if isinstance(progress_data.get(field), list):
                setattr(progress, field, progress_data[field])
        progress.updated_at = datetime.utcnow()
        self.session.add(progress)
        return True

    def _match_character(self, name: Optional[str], character_map: dict[str, Character]) -> Optional[Character]:
        if not name:
            return None
        name_text = str(name)
        for character_name, character in character_map.items():
            if character_name == name_text or character_name in name_text or name_text in character_name:
                return character
        return None

    def _bounded_importance(self, value: Any) -> int:
        try:
            importance = int(value)
        except (TypeError, ValueError):
            importance = 3
        return max(1, min(5, importance))


def extract_chapter_state_safely(session: Session, chapter: Chapter, content: str, context_prompt: str = "") -> dict:
    try:
        return ChapterStateExtractionService(session).extract_and_save(chapter, content, context_prompt)
    except Exception as exc:
        logger.warning("Chapter state extraction failed for chapter %s: %s", chapter.id, exc)
        session.rollback()
        return {"memories": 0, "character_states": 0, "progress_updated": False, "error": str(exc)}
