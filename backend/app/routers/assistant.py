from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlmodel import Session

from app.core.database import get_session
from app.cruds import crud_project
from app.schemas.schemas import (
    AgentConversationRead,
    AgentMessageCreate,
    AgentMessageRead,
    AssistantChatResponse,
)
from app.services.assistant_service import (
    AssistantError,
    archive_and_recreate_conversation,
    conversation_to_dict,
    create_user_message_and_task,
    get_or_create_default_conversation,
    list_messages,
    message_to_dict,
)
from app.services.task_dispatch import run_task

router = APIRouter()


@router.get("/{project_id}/assistant/conversation", response_model=AgentConversationRead)
def get_assistant_conversation(project_id: str, session: Session = Depends(get_session)):
    if not crud_project.get_project(session, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        conversation = get_or_create_default_conversation(session, project_id)
    except AssistantError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return conversation_to_dict(conversation)


@router.get("/{project_id}/assistant/messages", response_model=list[AgentMessageRead])
def get_assistant_messages(
    project_id: str,
    limit: int = Query(100, ge=1, le=200),
    before_id: int | None = Query(None),
    session: Session = Depends(get_session),
):
    if not crud_project.get_project(session, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
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
            session, project_id, body.content
        )
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
    return conversation_to_dict(conversation)
