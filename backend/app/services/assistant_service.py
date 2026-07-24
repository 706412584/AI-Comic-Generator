from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.models.models import (
    AgentConversation,
    AgentMessage,
    Chapter,
    Character,
    MemoryEntry,
    Outline,
    Project,
    ProjectProgress,
    SettingEntry,
    Task,
)

MAX_MESSAGE_CHARS = 8000
HISTORY_LIMIT = 20
HISTORY_CHAR_BUDGET = 12000
BRIEF_CHAPTER_LIMIT = 8
BRIEF_CHARACTER_LIMIT = 20
BRIEF_SETTING_LIMIT = 15
BRIEF_OUTLINE_LIMIT = 10
BRIEF_MEMORY_LIMIT = 3
ACTIVE_CHAT_STATUSES = ("pending", "processing")


class AssistantError(ValueError):
    pass


class AssistantBusyError(AssistantError):
    """同会话已有进行中的创作助手任务。"""

    def __init__(self, message: str, *, task_id: str | None = None):
        super().__init__(message)
        self.task_id = task_id


def get_active_assistant_chat_task(
    session: Session,
    project_id: str,
    conversation_id: int | None = None,
) -> Task | None:
    statement = (
        select(Task)
        .where(Task.project_id == project_id)
        .where(Task.type == "assistant_chat")
        .where(Task.status.in_(list(ACTIVE_CHAT_STATUSES)))
        .order_by(Task.created_at.desc())
    )
    for task in session.exec(statement).all():
        if conversation_id is None:
            return task
        payload = task.input_payload or {}
        if payload.get("conversation_id") == conversation_id:
            return task
    return None


def text_provider_supports_tools(session: Session) -> tuple[bool, str | None]:
    """返回 (supports_tools, provider_name)。无文本配置时视为不支持。"""
    from app.cruds.crud_config import get_active_config

    config = get_active_config(session, "text")
    if not config:
        return False, None
    provider = (config.provider or "").lower().replace("-", "_")
    return provider == "openai_compatible", provider


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


def list_conversations(
    session: Session,
    project_id: str,
    *,
    include_archived: bool = True,
    limit: int = 50,
) -> list[AgentConversation]:
    project = session.get(Project, project_id)
    if not project:
        raise AssistantError("Project not found")
    limit = max(1, min(limit, 100))
    statement = (
        select(AgentConversation)
        .where(AgentConversation.project_id == project_id)
        .order_by(AgentConversation.updated_at.desc())
        .limit(limit)
    )
    if not include_archived:
        statement = statement.where(AgentConversation.status == "active")
    return list(session.exec(statement).all())


def get_conversation_for_project(
    session: Session, project_id: str, conversation_id: int
) -> AgentConversation:
    conversation = session.get(AgentConversation, conversation_id)
    if not conversation or conversation.project_id != project_id:
        raise AssistantError("会话不存在")
    return conversation


def create_conversation(
    session: Session,
    project_id: str,
    *,
    title: str | None = None,
    activate: bool = True,
) -> AgentConversation:
    project = session.get(Project, project_id)
    if not project:
        raise AssistantError("Project not found")
    name = (title or "").strip() or f"会话 {datetime.utcnow().strftime('%m-%d %H:%M')}"
    if len(name) > 80:
        raise AssistantError("会话标题不能超过 80 字")
    if activate:
        # 多 active 允许；前端以最新 active 为主，此处不强制归档
        pass
    conversation = AgentConversation(project_id=project_id, title=name, status="active")
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def rename_conversation(
    session: Session, project_id: str, conversation_id: int, title: str
) -> AgentConversation:
    conversation = get_conversation_for_project(session, project_id, conversation_id)
    name = (title or "").strip()
    if not name:
        raise AssistantError("标题不能为空")
    if len(name) > 80:
        raise AssistantError("会话标题不能超过 80 字")
    conversation.title = name
    conversation.updated_at = datetime.utcnow()
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def archive_conversation(
    session: Session, project_id: str, conversation_id: int
) -> AgentConversation:
    conversation = get_conversation_for_project(session, project_id, conversation_id)
    cancel_active_assistant_chats(session, project_id, conversation.id)
    conversation.status = "archived"
    conversation.updated_at = datetime.utcnow()
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    # 若没有 active 会话则自动建一个
    active = session.exec(
        select(AgentConversation)
        .where(AgentConversation.project_id == project_id)
        .where(AgentConversation.status == "active")
    ).first()
    if not active:
        return create_conversation(session, project_id, title="创作助手")
    return conversation


def activate_conversation(
    session: Session, project_id: str, conversation_id: int
) -> AgentConversation:
    conversation = get_conversation_for_project(session, project_id, conversation_id)
    conversation.status = "active"
    conversation.updated_at = datetime.utcnow()
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

    # 设定按 importance 加权
    settings = session.exec(
        select(SettingEntry)
        .where(SettingEntry.project_id == project_id)
        .where(SettingEntry.is_active == True)  # noqa: E712
        .order_by(SettingEntry.importance.desc(), SettingEntry.id.desc())
    ).all()
    setting_titles = [
        f"{s.title}(★{s.importance or 0})" for s in settings[:BRIEF_SETTING_LIMIT] if s.title
    ]
    lines.append(f"设定条目: {', '.join(setting_titles) if setting_titles else '（无）'}")

    outlines = session.exec(
        select(Outline).where(Outline.project_id == project_id).order_by(Outline.sort_order)
    ).all()
    outline_titles = []
    for item in outlines[:BRIEF_OUTLINE_LIMIT]:
        title = getattr(item, "title", None) or getattr(item, "content", None) or str(item.id)
        outline_titles.append(_clip(title, 40))
    lines.append(f"大纲: {', '.join(outline_titles) if outline_titles else '（无）'}")

    progress = session.exec(
        select(ProjectProgress).where(ProjectProgress.project_id == project_id)
    ).first()
    focus_chapter_id = None
    if progress:
        progress_bits = [
            f"章节ID={progress.current_chapter_id or '无'}",
            f"弧线={progress.current_arc or '无'}",
            f"地点={progress.current_location or '无'}",
            f"时间={progress.current_time or '无'}",
        ]
        if progress.main_conflict:
            progress_bits.append(f"主冲突={_clip(progress.main_conflict, 120)}")
        if progress.notes:
            progress_bits.append(f"备注={_clip(progress.notes, 80)}")
        lines.append("当前进度: " + "；".join(progress_bits))
        focus_chapter_id = progress.current_chapter_id

        if progress.current_chapter_id:
            current_chapter = session.get(Chapter, progress.current_chapter_id)
            if current_chapter and current_chapter.project_id == project_id:
                lines.append(
                    f"当前章: [{current_chapter.sequence}] {current_chapter.title}"
                    f" — {_clip(current_chapter.summary or current_chapter.content, 200) or '（无摘要）'}"
                )

    # 记忆：重要性优先，其次最近
    memory_stmt = (
        select(MemoryEntry)
        .where(MemoryEntry.project_id == project_id)
        .where(MemoryEntry.is_active == True)  # noqa: E712
        .order_by(MemoryEntry.importance.desc(), MemoryEntry.id.desc())
        .limit(BRIEF_MEMORY_LIMIT + 2)
    )
    recent_memories = session.exec(memory_stmt).all()
    if recent_memories:
        lines.append("关键记忆:")
        for memory in recent_memories[:BRIEF_MEMORY_LIMIT]:
            lines.append(
                f"  - [★{getattr(memory, 'importance', 0) or 0}|{memory.memory_type or 'event'}] "
                f"{_clip(memory.content, 100)}"
            )

    # 若有当前章，附加 ContextAssemblyService 精简上下文
    if focus_chapter_id:
        try:
            from app.services.context_assembly_service import ContextAssemblyService

            cas = ContextAssemblyService(session)
            ctx = cas.build_chapter_context(project_id, int(focus_chapter_id))
            # 只取角色状态 / 关系 / 记忆的短摘要，避免 brief 爆炸
            rel_text = cas.render_relationships(ctx.get("relationships") or [])
            state_text = cas.render_states(ctx.get("states") or [])
            if rel_text and "暂无" not in rel_text:
                lines.append("当前章关系摘要:")
                lines.append(_clip(rel_text, 400))
            if state_text and "暂无" not in state_text:
                lines.append("当前章角色状态:")
                lines.append(_clip(state_text, 400))
        except Exception:
            pass

    return "\n".join(lines)


def format_assistant_error(exc: Exception) -> str:
    """把上游/内部异常收成用户可读文案。"""
    text = str(exc or "").strip() or "未知错误"
    lower = text.lower()
    if "api key" in lower or "unauthorized" in lower or "401" in lower:
        return "文本模型鉴权失败，请检查「模型配置」中的 API Key。"
    if "404" in lower and "model" in lower:
        return "文本模型不存在或名称错误，请在「模型配置」中确认 model_name。"
    if "connection" in lower or "timeout" in lower or "timed out" in lower:
        return f"连接模型服务失败：{_clip(text, 180)}"
    if "cancelled" in lower or "取消" in text:
        return "已取消生成"
    if "No active configuration" in text or "no active configuration" in lower:
        return "未配置文本模型，请先在「模型配置」中添加并设为默认。"
    if "not openai" in lower or "tool" in lower and "support" in lower:
        return text
    return _clip(text, 400)


def build_chat_system_prompt(brief: str, *, tools_enabled: bool = True) -> str:
    if tools_enabled:
        capability = """你可以使用工具读取与修改当前项目数据（章节、设定、角色、大纲、记忆、进度、分镜、关系等）。

规则：
1. 需要准确事实时先调用只读工具（get_project / list_chapters / search_chapters / get_chapter / get_character / get_setting / list_storyboard / list_relationships / search_* 等），不要臆造 ID 或内容。
2. 精读正文时优先 get_chapter(mode=segment) 分段读取，避免一次拉整章；搜章节用 search_chapters。
3. 用户明确要求修改结构化数据时，再调用 create_* / update_* 工具；改完后用一两句话确认改了什么。
4. 不要编造已生成的图片路径或任务 ID；派发任务后如实返回 task_id，并提醒用户看右下角任务面板。
5. 耗时生成请用 start_* 工具派发已有后台任务（一句话初始化 / 批量出图 / 角色绘制 / 章节正文 / 章节分镜 / 原文分析），不要假装已经画完或生成完；工具失败时说明原因并给出可执行建议。
6. 回答简洁、可执行；默认使用与项目 language 一致的语言（通常是中文）。
7. 单次回复尽量少轮工具调用；能一次读完就不要反复搜；同一类 start_* 不要重复连点。"""
    else:
        capability = """【能力限制】当前文本模型不是 OpenAI 兼容接口，无法使用工具读写项目或派发任务。
你只能基于下方项目摘要做讨论与建议；若用户要求改库/出图/生成，请明确说明需在「模型配置」中将文本默认改为 OpenAI 兼容供应商，或让用户使用页面上的对应按钮。"""

    return f"""你是「AI 漫画生成器」内的创作助手，帮助用户推进当前项目的故事、设定、角色与分镜规划。

{capability}

【项目摘要】
{brief}
"""


def build_chat_user_payload(history: list[AgentMessage], latest: str) -> str:
    """兼容旧路径：把历史压成单条 user 文本（优先用 build_chat_messages）。"""
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


def build_chat_messages(
    brief: str,
    history: list[AgentMessage],
    latest: str,
    *,
    tools_enabled: bool = True,
) -> list[dict[str, Any]]:
    """组装原生 multi-turn messages（system + 历史 + 当前 user）。"""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_chat_system_prompt(brief, tools_enabled=tools_enabled)},
    ]
    budget = HISTORY_CHAR_BUDGET
    selected: list[AgentMessage] = []
    for message in reversed(history):
        content = (message.content or "").strip()
        if not content:
            continue
        role = message.role if message.role in {"user", "assistant"} else "user"
        cost = len(content) + 16
        if selected and budget - cost < 0:
            break
        budget -= cost
        selected.append(message)
    for message in reversed(selected):
        role = message.role if message.role in {"user", "assistant"} else "user"
        content = (message.content or "").strip()
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": latest.strip()})
    return messages


def create_user_message_and_task(
    session: Session,
    project_id: str,
    content: str,
    *,
    conversation_id: int | None = None,
    allow_writes: bool = True,
    regenerate_from_message_id: int | None = None,
) -> tuple[AgentConversation, AgentMessage, Task]:
    text = (content or "").strip()
    if not text:
        raise AssistantError("消息内容不能为空")
    if len(text) > MAX_MESSAGE_CHARS:
        raise AssistantError(f"消息不能超过 {MAX_MESSAGE_CHARS} 字")

    if conversation_id is not None:
        conversation = get_conversation_for_project(session, project_id, conversation_id)
        if conversation.status != "active":
            conversation.status = "active"
            session.add(conversation)
    else:
        conversation = get_or_create_default_conversation(session, project_id)

    busy = get_active_assistant_chat_task(session, project_id, conversation.id)
    if busy:
        raise AssistantBusyError(
            "创作助手正在回复中，请等待完成后再发送",
            task_id=busy.id,
        )

    payload: dict[str, Any] = {}
    if regenerate_from_message_id is not None:
        payload["regenerate_from_message_id"] = regenerate_from_message_id

    user_message = AgentMessage(
        conversation_id=conversation.id,
        project_id=project_id,
        role="user",
        content=text,
        payload=payload,
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
            "allow_writes": bool(allow_writes),
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


def regenerate_assistant_message(
    session: Session,
    project_id: str,
    message_id: int,
    *,
    allow_writes: bool = True,
) -> tuple[AgentConversation, AgentMessage, Task]:
    """基于某条 user 消息重新生成助手回复；若传入 assistant 消息则找其前一条 user。"""
    message = session.get(AgentMessage, message_id)
    if not message or message.project_id != project_id:
        raise AssistantError("消息不存在")
    conversation = get_conversation_for_project(session, project_id, message.conversation_id)

    user_message = message
    if message.role == "assistant":
        user_message = session.exec(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation.id)
            .where(AgentMessage.role == "user")
            .where(AgentMessage.id < message.id)
            .order_by(AgentMessage.id.desc())
        ).first()
        if not user_message:
            raise AssistantError("找不到对应的用户消息，无法重新生成")
        # 软删除旧 assistant：清空内容标记为 superseded，保留历史痕迹
        message.payload = {**(message.payload or {}), "superseded": True}
        message.content = message.content or ""
        session.add(message)
    elif message.role != "user":
        raise AssistantError("只能对用户或助手消息重新生成")

    busy = get_active_assistant_chat_task(session, project_id, conversation.id)
    if busy:
        raise AssistantBusyError(
            "创作助手正在回复中，请等待完成后再发送",
            task_id=busy.id,
        )

    # 不新建 user 消息，复用原 user_message
    task = Task(
        type="assistant_chat",
        status="pending",
        project_id=project_id,
        name="创作助手重新生成",
        description="AI 正在重新生成回复",
        progress=0,
        message="等待重新生成...",
        input_payload={
            "project_id": project_id,
            "conversation_id": conversation.id,
            "user_message_id": user_message.id,
            "allow_writes": bool(allow_writes),
            "regenerate": True,
        },
    )
    session.add(task)
    conversation.updated_at = datetime.utcnow()
    session.add(conversation)
    session.commit()
    session.refresh(task)
    session.refresh(conversation)
    session.refresh(user_message)
    return conversation, user_message, task


def cancel_active_assistant_chats(session: Session, project_id: str, conversation_id: int | None = None) -> int:
    """将进行中的 assistant_chat 标为 cancelled。返回取消数量。"""
    cancelled = 0
    statement = (
        select(Task)
        .where(Task.project_id == project_id)
        .where(Task.type == "assistant_chat")
        .where(Task.status.in_(list(ACTIVE_CHAT_STATUSES)))
    )
    for task in session.exec(statement).all():
        if conversation_id is not None:
            payload = task.input_payload or {}
            if payload.get("conversation_id") != conversation_id:
                continue
        task.status = "cancelled"
        task.message = "会话已清空，任务已取消"
        task.updated_at = datetime.utcnow()
        session.add(task)
        cancelled += 1
    return cancelled


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
        cancel_active_assistant_chats(session, project_id, item.id)
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


def conversation_to_dict(
    conversation: AgentConversation,
    *,
    tools_enabled: bool | None = None,
    text_provider: str | None = None,
    active_task_id: str | None = None,
    message_count: int | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": conversation.id,
        "project_id": conversation.project_id,
        "title": conversation.title,
        "status": conversation.status,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }
    if tools_enabled is not None:
        data["tools_enabled"] = tools_enabled
    if text_provider is not None:
        data["text_provider"] = text_provider
    if active_task_id is not None:
        data["active_task_id"] = active_task_id
    if message_count is not None:
        data["message_count"] = message_count
    return data


def conversation_message_count(session: Session, conversation_id: int) -> int:
    rows = session.exec(
        select(AgentMessage).where(AgentMessage.conversation_id == conversation_id)
    ).all()
    return len(rows)
