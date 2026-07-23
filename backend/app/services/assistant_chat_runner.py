from __future__ import annotations

import json
import logging
import time
import traceback
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.core.database import engine
from app.models.models import AgentConversation, AgentMessage, Task
from app.services.ai_service import AIService
from app.services.assistant_service import (
    HISTORY_LIMIT,
    build_chat_system_prompt,
    build_chat_user_payload,
    build_project_brief,
)
from app.services.assistant_tools import (
    ToolError,
    execute_tool,
    openai_tool_definitions,
    parse_tool_arguments,
)

logger = logging.getLogger(__name__)

STREAM_FLUSH_INTERVAL_SECONDS = 1.0
STREAM_PREVIEW_MAX_CHARS = 3000
MAX_TOOL_ROUNDS = 6


def run_assistant_chat_task(task_id: str) -> None:
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            logger.error("Assistant chat task %s not found", task_id)
            return

        payload = dict(task.input_payload or {})
        project_id = payload.get("project_id") or task.project_id
        conversation_id = payload.get("conversation_id")
        user_message_id = payload.get("user_message_id")

        task.status = "processing"
        task.progress = 5
        task.message = "创作助手正在准备上下文..."
        task.updated_at = datetime.utcnow()
        session.add(task)
        session.commit()

        assistant_message: AgentMessage | None = None
        tool_trace: list[dict[str, Any]] = []
        try:
            if not project_id or conversation_id is None or user_message_id is None:
                raise ValueError("assistant_chat 任务缺少 project_id / conversation_id / user_message_id")

            conversation = session.get(AgentConversation, int(conversation_id))
            if not conversation or conversation.project_id != project_id:
                raise ValueError("会话不存在或不属于该项目")

            user_message = session.get(AgentMessage, int(user_message_id))
            if not user_message or user_message.conversation_id != conversation.id:
                raise ValueError("用户消息不存在")

            assistant_message = session.exec(
                select(AgentMessage)
                .where(AgentMessage.task_id == task_id)
                .where(AgentMessage.role == "assistant")
            ).first()
            if not assistant_message:
                assistant_message = AgentMessage(
                    conversation_id=conversation.id,
                    project_id=project_id,
                    role="assistant",
                    content="",
                    task_id=task_id,
                    payload={"streaming": True},
                )
                session.add(assistant_message)
                session.commit()
                session.refresh(assistant_message)

            task.progress = 15
            task.message = "正在组装项目摘要与对话历史..."
            task.updated_at = datetime.utcnow()
            session.add(task)
            session.commit()

            brief = build_project_brief(session, project_id)
            history = session.exec(
                select(AgentMessage)
                .where(AgentMessage.conversation_id == conversation.id)
                .where(AgentMessage.id < user_message.id)
                .order_by(AgentMessage.id.desc())
                .limit(HISTORY_LIMIT)
            ).all()
            history = list(reversed(history))
            system_prompt = build_chat_system_prompt(brief)
            user_payload = build_chat_user_payload(history, user_message.content)

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ]
            tools = openai_tool_definitions()
            ai = AIService(session)

            def raise_if_cancelled() -> None:
                session.refresh(task)
                if task.status == "cancelled":
                    raise RuntimeError("任务已被用户取消")

            def publish_progress(message: str, preview: str = "", progress: int | None = None) -> None:
                result = dict(task.result or {})
                if preview:
                    result["stream_preview"] = preview[-STREAM_PREVIEW_MAX_CHARS:]
                    result["stream_chars"] = len(preview)
                result["assistant_message_id"] = assistant_message.id
                result["tool_calls"] = tool_trace[-20:]
                task.result = result
                if progress is not None:
                    task.progress = progress
                task.message = message
                task.updated_at = datetime.utcnow()
                session.add(task)
                session.commit()

            final_text = ""
            for round_index in range(MAX_TOOL_ROUNDS):
                raise_if_cancelled()
                publish_progress(
                    f"AI 思考中（第 {round_index + 1} 轮）...",
                    preview=final_text or f"（工具轮次 {round_index + 1}）",
                    progress=min(85, 25 + round_index * 10),
                )

                response = ai.chat_completion(messages, tools=tools, tool_choice="auto")
                content = (response.get("content") or "") if isinstance(response.get("content"), str) else ""
                tool_calls = response.get("tool_calls") or []

                if tool_calls:
                    # Keep assistant message with tool_calls in transcript
                    assistant_turn: dict[str, Any] = {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": tool_calls,
                    }
                    messages.append(assistant_turn)

                    for call in tool_calls:
                        raise_if_cancelled()
                        call_id = call.get("id") or f"call_{len(tool_trace)}"
                        function = call.get("function") or {}
                        name = function.get("name") or ""
                        raw_args = function.get("arguments")
                        try:
                            arguments = parse_tool_arguments(raw_args)
                        except ToolError as exc:
                            tool_result = json.dumps(
                                {"ok": False, "error": str(exc)},
                                ensure_ascii=False,
                            )
                            tool_trace.append(
                                {"name": name or "?", "ok": False, "error": str(exc)}
                            )
                        else:
                            publish_progress(
                                f"正在执行工具：{name}...",
                                preview=final_text or f"调用工具 {name}",
                                progress=min(90, 30 + len(tool_trace) * 5),
                            )
                            try:
                                tool_result = execute_tool(session, project_id, name, arguments)
                                tool_trace.append({"name": name, "ok": True, "args": arguments})
                            except ToolError as exc:
                                tool_result = json.dumps(
                                    {"ok": False, "error": str(exc)},
                                    ensure_ascii=False,
                                )
                                tool_trace.append(
                                    {"name": name, "ok": False, "error": str(exc), "args": arguments}
                                )
                            except Exception as exc:
                                tool_result = json.dumps(
                                    {"ok": False, "error": str(exc)},
                                    ensure_ascii=False,
                                )
                                tool_trace.append(
                                    {"name": name, "ok": False, "error": str(exc)}
                                )

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": tool_result,
                            }
                        )
                    continue

                # No tool calls → final answer
                final_text = content.strip()
                if not final_text and tool_trace:
                    final_text = "已完成相关工具操作。"
                if not final_text:
                    final_text = "（模型未返回文本）"
                break
            else:
                # Exceeded rounds — ask model for a final summary without tools
                raise_if_cancelled()
                messages.append(
                    {
                        "role": "user",
                        "content": "请基于已完成的工具结果，用中文直接给出最终回复，不要再调用工具。",
                    }
                )
                response = ai.chat_completion(messages, tools=None, tool_choice=None)
                final_text = (response.get("content") or "").strip() or "已达到工具调用上限，请根据已有结果继续。"

            # Prefer streaming polish only when no tools were used (faster UX for pure chat)
            if not tool_trace:
                last_flush = {"at": 0.0}

                def on_delta(full_text: str, force: bool = False) -> None:
                    raise_if_cancelled()
                    now = time.monotonic()
                    if not force and now - last_flush["at"] < STREAM_FLUSH_INTERVAL_SECONDS:
                        return
                    last_flush["at"] = now
                    publish_progress(
                        f"AI 正在回复（已生成 {len(full_text)} 字）...",
                        preview=full_text,
                        progress=min(90, 20 + len(full_text) // 50),
                    )

                # Already have final_text from non-stream tool path; if pure chat used chat_completion,
                # optionally re-stream is wasteful. Keep final_text as-is.
                publish_progress("AI 正在回复...", preview=final_text, progress=80)
            else:
                publish_progress(
                    f"已执行 {len(tool_trace)} 次工具，正在整理回复...",
                    preview=final_text,
                    progress=92,
                )

            assistant_message.content = final_text
            assistant_message.payload = {
                "streaming": False,
                "tool_calls": tool_trace,
            }
            assistant_message.task_id = task_id
            session.add(assistant_message)

            conversation.updated_at = datetime.utcnow()
            session.add(conversation)

            task.status = "completed"
            task.progress = 100
            task.message = (
                f"回复已完成（工具 {len(tool_trace)} 次）" if tool_trace else "回复已完成"
            )
            result = dict(task.result or {})
            result["assistant_message_id"] = assistant_message.id
            result["stream_preview"] = final_text[-STREAM_PREVIEW_MAX_CHARS:]
            result["stream_chars"] = len(final_text)
            result["tool_calls"] = tool_trace
            task.result = result
            task.updated_at = datetime.utcnow()
            session.add(task)
            session.commit()
        except Exception as exc:
            logger.error("Assistant chat task %s failed: %s", task_id, exc)
            traceback.print_exc()
            session.rollback()

            task = session.get(Task, task_id)
            if not task:
                return
            if task.status == "cancelled":
                return

            if assistant_message and assistant_message.id:
                msg = session.get(AgentMessage, assistant_message.id)
                if msg:
                    msg.content = msg.content or f"（生成失败）{exc}"
                    msg.payload = {
                        "streaming": False,
                        "error": str(exc),
                        "tool_calls": tool_trace,
                    }
                    session.add(msg)

            task.status = "failed"
            task.message = str(exc)
            result = dict(task.result or {})
            result["tool_calls"] = tool_trace
            task.result = result
            task.updated_at = datetime.utcnow()
            session.add(task)
            session.commit()
