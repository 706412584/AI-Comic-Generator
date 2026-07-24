from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlmodel import Session

from app.core.database import get_session
from app.cruds import crud_project
from app.schemas.schemas import (
    AgentConversationCreate,
    AgentConversationRead,
    AgentConversationUpdate,
    AgentMessageCreate,
    AgentMessageRead,
    AssistantChatResponse,
    AssistantRegenerateRequest,
)
from app.services.assistant_service import (
    AssistantBusyError,
    AssistantError,
    activate_conversation,
    archive_and_recreate_conversation,
    archive_conversation,
    conversation_message_count,
    conversation_to_dict,
    create_conversation,
    create_user_message_and_task,
    get_active_assistant_chat_task,
    get_conversation_for_project,
    get_or_create_default_conversation,
    list_conversations,
    list_messages,
    message_to_dict,
    regenerate_assistant_message,
    rename_conversation,
    text_provider_supports_tools,
)
from app.services.task_dispatch import run_task

router = APIRouter()


def _conversation_payload(session: Session, conversation, *, with_meta: bool = True) -> dict:
    if not with_meta:
        return conversation_to_dict(conversation)
    tools_enabled, provider = text_provider_supports_tools(session)
    active = get_active_assistant_chat_task(session, conversation.project_id, conversation.id)
    return conversation_to_dict(
        conversation,
        tools_enabled=tools_enabled,
        text_provider=provider,
        active_task_id=active.id if active else None,
        message_count=conversation_message_count(session, conversation.id),
    )


@router.get("/{project_id}/assistant/conversation", response_model=AgentConversationRead)
def get_assistant_conversation(project_id: str, session: Session = Depends(get_session)):
    if not crud_project.get_project(session, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        conversation = get_or_create_default_conversation(session, project_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _conversation_payload(session, conversation)


@router.get("/{project_id}/assistant/conversations", response_model=list[AgentConversationRead])
def get_assistant_conversations(
    project_id: str,
    include_archived: bool = Query(True),
    limit: int = Query(50, ge=1, le=100),
    session: Session = Depends(get_session),
):
    if not crud_project.get_project(session, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        rows = list_conversations(
            session, project_id, include_archived=include_archived, limit=limit
        )
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        conversation_to_dict(
            item,
            message_count=conversation_message_count(session, item.id),
            active_task_id=(
                (get_active_assistant_chat_task(session, project_id, item.id) or type("T", (), {"id": None})()).id
            ),
        )
        for item in rows
    ]


@router.post("/{project_id}/assistant/conversations", response_model=AgentConversationRead)
def post_assistant_conversation(
    project_id: str,
    body: AgentConversationCreate,
    session: Session = Depends(get_session),
):
    if not crud_project.get_project(session, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        conversation = create_conversation(session, project_id, title=body.title)
    except AssistantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _conversation_payload(session, conversation)


@router.patch(
    "/{project_id}/assistant/conversations/{conversation_id}",
    response_model=AgentConversationRead,
)
def patch_assistant_conversation(
    project_id: str,
    conversation_id: int,
    body: AgentConversationUpdate,
    session: Session = Depends(get_session),
):
    if not crud_project.get_project(session, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        conversation = get_conversation_for_project(session, project_id, conversation_id)
        if body.title is not None:
            conversation = rename_conversation(session, project_id, conversation_id, body.title)
        if body.status == "archived":
            conversation = archive_conversation(session, project_id, conversation_id)
        elif body.status == "active":
            conversation = activate_conversation(session, project_id, conversation_id)
        elif body.status is not None and body.status not in {"active", "archived"}:
            raise AssistantError("status 只能是 active 或 archived")
    except AssistantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _conversation_payload(session, conversation)


@router.get("/{project_id}/assistant/messages", response_model=list[AgentMessageRead])
def get_assistant_messages(
    project_id: str,
    conversation_id: int | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
    before_id: int | None = Query(None),
    session: Session = Depends(get_session),
):
    if not crud_project.get_project(session, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        if conversation_id is not None:
            conversation = get_conversation_for_project(session, project_id, conversation_id)
        else:
            conversation = get_or_create_default_conversation(session, project_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    messages = list_messages(session, conversation.id, limit=limit, before_id=before_id)
    return [message_to_dict(item) for item in messages]


@router.post("/{project_id}/assistant/messages", response_model=AssistantChatResponse)
def post_assistant_message(
    project_id: str,
    body: AgentMessageCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    if not crud_project.get_project(session, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        conversation, user_message, task = create_user_message_and_task(
            session,
            project_id,
            body.content,
            conversation_id=body.conversation_id,
            allow_writes=True if body.allow_writes is None else bool(body.allow_writes),
        )
    except AssistantBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "task_id": exc.task_id},
        ) from exc
    except AssistantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(run_task, task.id, task.type, dict(task.input_payload or {}))
    return {
        "conversation_id": conversation.id,
        "user_message": message_to_dict(user_message),
        "task_id": task.id,
    }


@router.post(
    "/{project_id}/assistant/messages/{message_id}/regenerate",
    response_model=AssistantChatResponse,
)
def regenerate_message(
    project_id: str,
    message_id: int,
    background_tasks: BackgroundTasks,
    body: AssistantRegenerateRequest | None = None,
    session: Session = Depends(get_session),
):
    if not crud_project.get_project(session, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    allow_writes = True if not body or body.allow_writes is None else bool(body.allow_writes)
    try:
        conversation, user_message, task = regenerate_assistant_message(
            session, project_id, message_id, allow_writes=allow_writes
        )
    except AssistantBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "task_id": exc.task_id},
        ) from exc
    except AssistantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(run_task, task.id, task.type, dict(task.input_payload or {}))
    return {
        "conversation_id": conversation.id,
        "user_message": message_to_dict(user_message),
        "task_id": task.id,
    }


@router.post("/{project_id}/assistant/conversation/clear", response_model=AgentConversationRead)
def clear_assistant_conversation(project_id: str, session: Session = Depends(get_session)):
    if not crud_project.get_project(session, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        conversation = archive_and_recreate_conversation(session, project_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _conversation_payload(session, conversation)
