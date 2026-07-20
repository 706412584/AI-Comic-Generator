from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, or_, select

from app.models.models import (
    Chapter,
    Character,
    CharacterRelationship,
    CharacterState,
    MemoryEntry,
    Outline,
    Project,
    ProjectProgress,
    SettingEntry,
    SourceChapter,
    SourceImport,
)


class ContextAssemblyService:
    def __init__(self, session: Session):
        self.session = session

    def build_chapter_context(self, project_id: str, chapter_id: int) -> dict:
        project = self.session.get(Project, project_id)
        chapter = self.session.get(Chapter, chapter_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        if not chapter or chapter.project_id != project_id:
            raise ValueError(f"Chapter not found in project: {chapter_id}")

        progress = self.get_progress(project_id)
        outlines = self.get_outlines(project_id, chapter_id)
        settings = self.get_active_settings(project_id)
        characters = self.get_characters(project_id)
        relationships = self.get_relationships(project_id, chapter_id)
        states = self.get_character_states(project_id, chapter_id)
        memories = self.get_relevant_memories(project_id, chapter_id)
        source_context = self.build_source_context_for_chapter(chapter)

        return {
            "project": project,
            "chapter": chapter,
            "progress": progress,
            "outlines": outlines,
            "settings": settings,
            "characters": characters,
            "relationships": relationships,
            "states": states,
            "memories": memories,
            "source_context": source_context,
        }

    def get_progress(self, project_id: str) -> Optional[ProjectProgress]:
        statement = select(ProjectProgress).where(ProjectProgress.project_id == project_id)
        return self.session.exec(statement).first()

    def build_source_context_for_chapter(self, chapter: Chapter) -> dict:
        source_chapter = None
        if chapter.source_chapter_id:
            source_chapter = self.session.get(SourceChapter, chapter.source_chapter_id)
            if source_chapter and source_chapter.project_id != chapter.project_id:
                source_chapter = None

        if not source_chapter:
            return {}

        source_import = self.session.get(SourceImport, source_chapter.source_import_id)
        previous_chapter = self.session.exec(
            select(SourceChapter)
            .where(SourceChapter.source_import_id == source_chapter.source_import_id)
            .where(SourceChapter.sequence == source_chapter.sequence - 1)
        ).first()
        next_chapter = self.session.exec(
            select(SourceChapter)
            .where(SourceChapter.source_import_id == source_chapter.source_import_id)
            .where(SourceChapter.sequence == source_chapter.sequence + 1)
        ).first()
        return {
            "source_chapter": source_chapter,
            "source_import": source_import,
            "previous_summary": previous_chapter.summary_short if previous_chapter else None,
            "next_summary": next_chapter.summary_short if next_chapter else None,
        }

    def get_outlines(self, project_id: str, chapter_id: int) -> List[Outline]:
        statement = (
            select(Outline)
            .where(Outline.project_id == project_id)
            .where(or_(Outline.chapter_id.is_(None), Outline.chapter_id == chapter_id))
            .order_by(Outline.chapter_id.is_not(None), Outline.sort_order, Outline.id)
        )
        return list(self.session.exec(statement).all())

    def get_active_settings(self, project_id: str) -> List[SettingEntry]:
        statement = (
            select(SettingEntry)
            .where(SettingEntry.project_id == project_id)
            .where(SettingEntry.is_active == True)
            .order_by(SettingEntry.importance.desc(), SettingEntry.id)
        )
        return list(self.session.exec(statement).all())

    def get_characters(self, project_id: str) -> List[Character]:
        statement = select(Character).where(Character.project_id == project_id).order_by(Character.id)
        characters = list(self.session.exec(statement).all())
        for character in characters:
            _ = list(character.outfits)
        return characters

    def get_relationships(self, project_id: str, chapter_id: int) -> List[CharacterRelationship]:
        statement = (
            select(CharacterRelationship)
            .where(CharacterRelationship.project_id == project_id)
            .where(or_(CharacterRelationship.chapter_id.is_(None), CharacterRelationship.chapter_id == chapter_id))
            .order_by(CharacterRelationship.chapter_id.is_not(None), CharacterRelationship.intensity.desc(), CharacterRelationship.id)
        )
        relationships = list(self.session.exec(statement).all())
        for relationship in relationships:
            _ = relationship.source_character
            _ = relationship.target_character
        return relationships

    def get_character_states(self, project_id: str, chapter_id: int) -> List[CharacterState]:
        statement = (
            select(CharacterState)
            .where(CharacterState.project_id == project_id)
            .where(or_(CharacterState.chapter_id.is_(None), CharacterState.chapter_id == chapter_id))
            .order_by(CharacterState.chapter_id.is_not(None), CharacterState.id)
        )
        states = list(self.session.exec(statement).all())
        for state in states:
            _ = state.character
            _ = state.outfit
        return states

    def get_relevant_memories(self, project_id: str, chapter_id: int) -> List[MemoryEntry]:
        statement = (
            select(MemoryEntry)
            .where(MemoryEntry.project_id == project_id)
            .where(MemoryEntry.is_active == True)
            .where(MemoryEntry.scope.in_(["project", "chapter"]))
            .where(or_(MemoryEntry.chapter_id.is_(None), MemoryEntry.chapter_id == chapter_id))
            .where(MemoryEntry.importance >= 3)
            .order_by(MemoryEntry.importance.desc(), MemoryEntry.updated_at.desc(), MemoryEntry.id.desc())
            .limit(30)
        )
        memories = list(self.session.exec(statement).all())
        for memory in memories:
            _ = memory.character
        return memories

    def render_context_prompt(self, context: dict) -> str:
        project = context["project"]
        return (
            "你是长篇漫画/小说改漫创作助手。必须严格遵守以下项目上下文。\n\n"
            f"【项目】\n标题：{project.title}\n"
            f"主题：{project.theme or '未指定'}\n"
            f"语言：{project.language or 'zh-CN'}\n"
            f"描述：{project.description or '未提供'}\n\n"
            f"【当前进度】\n{self.render_progress(context['progress'])}\n\n"
            f"【当前章节】\n{self.render_chapter(context['chapter'])}\n\n"
            f"【原文章节上下文】\n{self.render_source_context(context.get('source_context') or {})}\n\n"
            f"【大纲/小纲】\n{self.render_outlines(context['outlines'])}\n\n"
            f"【世界设定】\n{self.render_settings(context['settings'])}\n\n"
            f"【角色】\n{self.render_characters(context['characters'])}\n\n"
            f"【人物关系】\n{self.render_relationships(context['relationships'])}\n\n"
            f"【角色当前状态】\n{self.render_states(context['states'])}\n\n"
            f"【记忆与连续性约束】\n{self.render_memories(context['memories'])}"
        )

    def render_progress(self, progress: Optional[ProjectProgress]) -> str:
        if not progress:
            return "暂无项目进度记录。"

        lines = [
            f"当前章节ID：{progress.current_chapter_id or '未设置'}",
            f"当前篇章：{progress.current_arc or '未设置'}",
            f"当前地点：{progress.current_location or '未设置'}",
            f"当前时间：{progress.current_time or '未设置'}",
            f"主冲突：{progress.main_conflict or '未设置'}",
            f"进行中的线索：{self.render_list(progress.active_threads)}",
            f"已解决线索：{self.render_list(progress.resolved_threads)}",
            f"待回收伏笔：{self.render_list(progress.pending_hooks)}",
            f"备注：{progress.notes or '无'}",
        ]
        return "\n".join(lines)

    def render_chapter(self, chapter: Chapter) -> str:
        metadata = chapter.chapter_metadata or {}
        metadata_text = self.render_key_value_map(metadata)
        lines = [
            f"章节序号：{chapter.sequence}",
            f"章节标题：{chapter.title}",
            f"章节摘要：{chapter.summary or '无'}",
            f"章节目标：{chapter.goal or '无'}",
            f"章节冲突：{chapter.conflict or '无'}",
            f"当前地点：{chapter.current_location or '未设置'}",
            f"当前时间：{chapter.current_time or '未设置'}",
            f"视角角色：{chapter.pov_character or '未设置'}",
            f"状态：{chapter.status}",
            f"元数据：{metadata_text}",
        ]
        return "\n".join(lines)

    def render_source_context(self, source_context: dict) -> str:
        if not source_context:
            return "当前章节未关联原文章节。"

        source_chapter = source_context.get("source_chapter")
        source_import = source_context.get("source_import")
        if not source_chapter:
            return "当前章节未关联原文章节。"

        source_text = source_chapter.raw_text or ""
        if len(source_text) > 20000:
            source_text = f"{source_text[:9000]}\n\n……【原文章节中段已截断】……\n\n{source_text[-9000:]}"

        lines = [
            f"原文文件：{source_import.file_name if source_import else '未知'}",
            f"全书摘要：{source_import.book_summary if source_import and source_import.book_summary else '暂无'}",
            f"原文章节序号：{source_chapter.sequence}",
            f"原文章节标题：{source_chapter.title}",
            f"原文章节摘要：{source_chapter.summary_short or '暂无'}",
            f"上一章摘要：{source_context.get('previous_summary') or '无'}",
            f"下一章摘要：{source_context.get('next_summary') or '无'}",
            "原文章节正文：",
            source_text,
        ]
        return "\n".join(lines)

    def render_outlines(self, outlines: List[Outline]) -> str:
        if not outlines:
            return "暂无大纲或小纲。"

        rendered = []
        for outline in outlines:
            scope_label = "章节小纲" if outline.chapter_id else "项目大纲"
            rendered.append(
                f"- [{scope_label}] {outline.title}\n"
                f"  内容：{outline.content}"
            )
        return "\n".join(rendered)

    def render_settings(self, settings: List[SettingEntry]) -> str:
        if not settings:
            return "暂无启用中的世界设定。"

        rendered = []
        for setting in settings:
            category_name = setting.category.name if setting.category else "未分类"
            tags_text = self.render_list(setting.tags)
            rendered.append(
                f"- {setting.title}（分类：{category_name}，重要度：{setting.importance}）\n"
                f"  内容：{setting.content}\n"
                f"  标签：{tags_text}"
            )
        return "\n".join(rendered)

    def render_characters(self, characters: List[Character]) -> str:
        if not characters:
            return "暂无角色信息。"

        rendered = []
        for character in characters:
            outfit_text = self.render_outfits(character)
            aliases_text = self.render_list(character.aliases)
            rendered.append(
                f"- {character.name}\n"
                f"  简介：{character.summary or '无'}\n"
                f"  别名：{aliases_text}\n"
                f"  状态：{character.status or '未设置'}\n"
                f"  服饰：{outfit_text}"
            )
        return "\n".join(rendered)

    def render_outfits(self, character: Character) -> str:
        outfits = list(character.outfits or [])
        if not outfits:
            return "无"

        rendered = []
        for outfit in outfits:
            default_mark = "（默认）" if outfit.is_default else ""
            description = outfit.description or "无描述"
            state = f"，状态：{outfit.state}" if outfit.state else ""
            rendered.append(f"{outfit.name}{default_mark}：{description}{state}")
        return "；".join(rendered)

    def render_relationships(self, relationships: List[CharacterRelationship]) -> str:
        if not relationships:
            return "暂无人物关系。"

        rendered = []
        for relationship in relationships:
            scope_label = "章节关系" if relationship.chapter_id else "项目关系"
            rendered.append(
                f"- [{scope_label}] {relationship.source_character.name} -> {relationship.target_character.name}\n"
                f"  类型：{relationship.relationship_type}，强度：{relationship.intensity}，状态：{relationship.status}\n"
                f"  描述：{relationship.description or '无'}"
            )
        return "\n".join(rendered)

    def render_states(self, states: List[CharacterState]) -> str:
        if not states:
            return "暂无角色状态。"

        rendered = []
        for state in states:
            scope_label = "章节状态" if state.chapter_id else "项目状态"
            outfit_name = state.outfit.name if state.outfit else "未设置"
            rendered.append(
                f"- [{scope_label}] {state.character.name}\n"
                f"  身体：{state.physical_state or '未设置'}，情绪：{state.emotional_state or '未设置'}\n"
                f"  地点：{state.location or '未设置'}，服饰：{outfit_name}\n"
                f"  目标：{state.goal or '无'}，秘密：{state.secret or '无'}\n"
                f"  战力：{state.power_level or '未设置'}，携带物：{self.render_list(state.inventory)}\n"
                f"  备注：{state.notes or '无'}"
            )
        return "\n".join(rendered)

    def render_memories(self, memories: List[MemoryEntry]) -> str:
        if not memories:
            return "暂无可用记忆。"

        rendered = []
        for memory in memories:
            scope_label = "章节记忆" if memory.chapter_id else "项目记忆"
            character_name = memory.character.name if memory.character else "无关联角色"
            rendered.append(
                f"- [{scope_label}] 重要度{memory.importance} / 类型：{memory.memory_type}\n"
                f"  角色：{character_name}\n"
                f"  内容：{memory.content}"
            )
        return "\n".join(rendered)

    @staticmethod
    def render_list(values: Optional[List[Any]]) -> str:
        if not values:
            return "无"
        return "、".join(str(value) for value in values)

    @staticmethod
    def render_key_value_map(data: Dict[str, Any]) -> str:
        if not data:
            return "无"
        return "；".join(f"{key}={value}" for key, value in data.items())
