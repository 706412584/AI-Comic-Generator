from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.models.models import (
    AgentConversation,
    AgentMessage,
    Chapter,
    Character,
    Outline,
    Project,
    ProjectProgress,
    SettingEntry,
    Task,
)

MAX_MESSAGE_CHARS = 8000
HISTORY_LIMIT = 20
BRIEF_CHAPTER_LIMIT = 8
BRIEF_CHARACTER_LIMIT = 20
BRIEF_SETTING_LIMIT = 15
BRIEF_OUTLINE_LIMIT = 10


class AssistantError(ValueError):
    pass


def get_or_create_default_conversation(session: Session, project_id: str) -> AgentConversation:
    project = session.get(Project, project_id)
    if not project:
        raise AssistantError("Project not found")

    conversation = session.exec(
        select(AgentConversation)
        .where(AgentConversation.project_id == project_id)
        .where(AgentConversation.status == "active")
        .order_by(AgentConversation.updated_at.desc())
    ).first()
    if conversation:
        return conversation

    conversation = AgentConversation(project_id=project_id, title="创作助手", status="active")
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def list_messages(
    session: Session,
    conversation_id: int,
    *,
    limit: int = 100,
    before_id: int | None = None,
) -> list[AgentMessage]:
    limit = max(1, min(limit, 200))
    statement = (
        select(AgentMessage)
        .where(AgentMessage.conversation_id == conversation_id)
        .order_by(AgentMessage.id.desc())
        .limit(limit)
    )
    if before_id is not None:
        statement = statement.where(AgentMessage.id < before_id)
    rows = list(session.exec(statement).all())
    rows.reverse()
    return rows


def _clip(text: Any, max_len: int) -> str:
    value = str(text or "").strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"


def build_project_brief(session: Session, project_id: str) -> str:
    project = session.get(Project, project_id)
    if not project:
        raise AssistantError("Project not found")

    lines = [
        f"标题: {project.title}",
        f"描述: {_clip(project.description, 300) or '（无）'}",
        f"主题: {project.theme or '（无）'}",
        f"语言: {project.language or 'zh-CN'}",
        f"工作流: {project.workflow_mode or 'comic'}",
    ]

    chapters = session.exec(
        select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.sequence)
    ).all()
    lines.append(f"章节数: {len(chapters)}")
    for chapter in chapters[:BRIEF_CHAPTER_LIMIT]:
        lines.append(
            f"  - [{chapter.sequence}] {chapter.title}: {_clip(chapter.summary, 80) or '（无摘要）'}"
        )
    if len(chapters) > BRIEF_CHAPTER_LIMIT:
        lines.append(f"  - … 另有 {len(chapters) - BRIEF_CHAPTER_LIMIT} 章")

    characters = session.exec(select(Character).where(Character.project_id == project_id)).all()
    names = [c.name for c in characters[:BRIEF_CHARACTER_LIMIT] if c.name]
    lines.append(f"角色: {', '.join(names) if names else '（无）'}")
    if len(characters) > BRIEF_CHARACTER_LIMIT:
        lines.append(f"  （另有 {len(characters) - BRIEF_CHARACTER_LIMIT} 名未列出）")

    settings = session.exec(select(SettingEntry).where(SettingEntry.project_id == project_id)).all()
    setting_titles = [s.title for s in settings[:BRIEF_SETTING_LIMIT] if s.title]
    lines.append(f"设定条目: {', '.join(setting_titles) if setting_titles else '（无）'}")

    outlines = session.exec(select(Outline).where(Outline.project_id == project_id)).all()
    outline_titles = []
    for item in outlines[:BRIEF_OUTLINE_LIMIT]:
        title = getattr(item, "title", None) or getattr(item, "content", None) or str(item.id)
        outline_titles.append(_clip(title, 40))
    lines.append(f"大纲: {', '.join(outline_titles) if outline_titles else '（无）'}")

    progress = session.exec(
        select(ProjectProgress).where(ProjectProgress.project_id == project_id)
    ).first()
    if progress:
        progress_bits = [
            f"章节ID={progress.current_chapter_id or '无'}",
            f"弧线={progress.current_arc or '无'}",
            f"地点={progress.current_location or '无'}",
            f"时间={progress.current_time or '无'}",
        ]
        if progress.main_conflict:
            progress_bits.append(f"主冲突={_clip(progress.main_conflict, 80)}")
        if progress.notes:
            progress_bits.append(f"备注={_clip(progress.notes, 80)}")
        lines.append("当前进度: " + "；".join(progress_bits))

    return "\n".join(lines)


def build_chat_system_prompt(brief: str) -> str:
    return f"""你是「AI 漫画生成器」内的创作助手，帮助用户推进当前项目的故事、设定、角色与分镜规划。

你可以使用工具读取与修改当前项目数据（章节、设定、角色、大纲、记忆、进度等）。

规则：
1. 需要准确事实时先调用只读工具（get_project / list_chapters / get_chapter / search_* 等），不要臆造 ID 或内容。
2. 用户明确要求修改时，再调用 create_* / update_* 工具；改完后用一两句话确认改了什么。
3. 不要编造已生成的图片路径或任务 ID。
4. 耗时生成（批量出图、一句话初始化、原文分析、批量分镜）没有对应写库工具时，指导用户使用界面按钮，不要假装已执行。
5. 回答简洁、可执行；默认使用与项目 language 一致的语言（通常是中文）。
6. 单次回复尽量少轮工具调用；能一次读完就不要反复搜。

【项目摘要】
{brief}
"""


def build_chat_user_payload(history: list[AgentMessage], latest: str) -> str:
    parts = ["### 对话历史"]
    if not history:
        parts.append("（暂无历史）")
    else:
        for message in history:
            role = message.role if message.role in {"user", "assistant", "system"} else "user"
            content = (message.content or "").strip()
            if not content:
                continue
            parts.append(f"[{role}]: {content}")
    parts.append("### 当前用户")
    parts.append(latest.strip())
    return "\n".join(parts)


def create_user_message_and_task(
    session: Session,
    project_id: str,
    content: str,
) -> tuple[AgentConversation, AgentMessage, Task]:
    text = (content or "").strip()
    if not text:
        raise AssistantError("消息内容不能为空")
    if len(text) > MAX_MESSAGE_CHARS:
        raise AssistantError(f"消息不能超过 {MAX_MESSAGE_CHARS} 字")

    conversation = get_or_create_default_conversation(session, project_id)

    user_message = AgentMessage(
        conversation_id=conversation.id,
        project_id=project_id,
        role="user",
        content=text,
        payload={},
    )
    session.add(user_message)
    session.flush()

    task = Task(
        type="assistant_chat",
        status="pending",
        project_id=project_id,
        name="创作助手回复",
        description="AI 正在根据项目上下文回复",
        progress=0,
        message="等待生成回复...",
        input_payload={
            "project_id": project_id,
            "conversation_id": conversation.id,
            "user_message_id": user_message.id,
        },
    )
    session.add(task)
    conversation.updated_at = datetime.utcnow()
    session.add(conversation)
    session.commit()
    session.refresh(user_message)
    session.refresh(task)
    session.refresh(conversation)
    return conversation, user_message, task


def archive_and_recreate_conversation(session: Session, project_id: str) -> AgentConversation:
    """Soft-clear: archive active conversations and create a fresh default session."""
    project = session.get(Project, project_id)
    if not project:
        raise AssistantError("Project not found")

    actives = session.exec(
        select(AgentConversation)
        .where(AgentConversation.project_id == project_id)
        .where(AgentConversation.status == "active")
    ).all()
    now = datetime.utcnow()
    for item in actives:
        item.status = "archived"
        item.updated_at = now
        session.add(item)

    conversation = AgentConversation(project_id=project_id, title="创作助手", status="active")
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def message_to_dict(message: AgentMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "project_id": message.project_id,
        "role": message.role,
        "content": message.content,
        "intent": message.intent,
        "task_id": message.task_id,
        "payload": message.payload or {},
        "created_at": message.created_at,
    }


def conversation_to_dict(conversation: AgentConversation) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "project_id": conversation.project_id,
        "title": conversation.title,
        "status": conversation.status,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }
