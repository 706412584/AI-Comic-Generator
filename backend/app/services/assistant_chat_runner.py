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
    build_chat_messages,
    build_project_brief,
    format_assistant_error,
    text_provider_supports_tools,
)
from app.services.assistant_tools import (
    ToolError,
    execute_tool,
    openai_tool_definitions,
    parse_tool_arguments,
)

logger = logging.getLogger(__name__)

STREAM_FLUSH_INTERVAL_SECONDS = 0.4
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
        allow_writes = payload.get("allow_writes", True)
        if allow_writes is None:
            allow_writes = True
        allow_writes = bool(allow_writes)

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

            tools_enabled, provider_name = text_provider_supports_tools(session)

            task.progress = 15
            task.message = "正在组装项目摘要与对话历史..."
            task.updated_at = datetime.utcnow()
            result = dict(task.result or {})
            result["tools_enabled"] = tools_enabled
            result["text_provider"] = provider_name
            result["allow_writes"] = allow_writes
            result["assistant_message_id"] = assistant_message.id
            task.result = result
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
            # 过滤已 superseded 的助手消息，避免污染上下文
            history = [
                m
                for m in history
                if not (m.role == "assistant" and (m.payload or {}).get("superseded"))
            ]
            messages = build_chat_messages(
                brief,
                history,
                user_message.content or "",
                tools_enabled=tools_enabled,
            )
            if tools_enabled and not allow_writes:
                messages[0]["content"] = (
                    messages[0]["content"]
                    + "\n\n【本轮约束】用户关闭了写库权限：禁止调用 create_* / update_* / start_*，"
                    "只能用只读工具；若用户要求修改，请说明需开启「允许写库」。"
                )
            tools = openai_tool_definitions() if tools_enabled else None
            ai = AIService(session)

            WRITE_PREFIXES = ("create_", "update_", "start_")

            def raise_if_cancelled() -> None:
                session.refresh(task)
                if task.status == "cancelled":
                    raise RuntimeError("任务已被用户取消")

            def publish_progress(
                message: str,
                preview: str = "",
                progress: int | None = None,
                *,
                round_index: int | None = None,
            ) -> None:
                result = dict(task.result or {})
                if preview:
                    result["stream_preview"] = preview[-STREAM_PREVIEW_MAX_CHARS:]
                    result["stream_chars"] = len(preview)
                result["assistant_message_id"] = assistant_message.id
                result["tool_calls"] = tool_trace[-20:]
                result["tools_enabled"] = tools_enabled
                result["text_provider"] = provider_name
                if round_index is not None:
                    result["round_index"] = round_index
                task.result = result
                if progress is not None:
                    task.progress = progress
                task.message = message
                task.updated_at = datetime.utcnow()
                session.add(task)
                session.commit()

            final_text = ""

            if not tools_enabled:
                # 非 OpenAI 兼容：无工具，直接真流式多轮 messages
                last_flush = {"at": 0.0}

                def on_delta(full_text: str) -> None:
                    raise_if_cancelled()
                    now = time.monotonic()
                    if now - last_flush["at"] < STREAM_FLUSH_INTERVAL_SECONDS:
                        return
                    last_flush["at"] = now
                    publish_progress(
                        f"AI 正在回复（已生成 {len(full_text)} 字）...",
                        preview=full_text,
                        progress=min(90, 20 + len(full_text) // 50),
                        round_index=1,
                    )

                publish_progress("AI 正在回复...", progress=25, round_index=1)
                final_text = (ai.chat_completion_stream(messages, on_delta=on_delta) or "").strip()
                if not final_text:
                    final_text = "（模型未返回文本）"
                publish_progress("AI 正在回复...", preview=final_text, progress=92, round_index=1)
            else:
                for round_index in range(MAX_TOOL_ROUNDS):
                    raise_if_cancelled()
                    publish_progress(
                        f"AI 思考中（第 {round_index + 1} 轮）...",
                        preview=final_text or f"（工具轮次 {round_index + 1}）",
                        progress=min(85, 25 + round_index * 10),
                        round_index=round_index + 1,
                    )

                    response = ai.chat_completion(messages, tools=tools, tool_choice="auto")
                    content = (
                        (response.get("content") or "")
                        if isinstance(response.get("content"), str)
                        else ""
                    )
                    tool_calls = response.get("tool_calls") or []

                    if tool_calls:
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
                                if not allow_writes and any(name.startswith(p) for p in WRITE_PREFIXES):
                                    err = "本轮已关闭写库/派发权限，无法执行该工具"
                                    tool_result = json.dumps(
                                        {"ok": False, "error": err},
                                        ensure_ascii=False,
                                    )
                                    tool_trace.append(
                                        {
                                            "name": name,
                                            "ok": False,
                                            "error": err,
                                            "args": arguments,
                                            "blocked": True,
                                        }
                                    )
                                    messages.append(
                                        {
                                            "role": "tool",
                                            "tool_call_id": call_id,
                                            "content": tool_result,
                                        }
                                    )
                                    continue

                                publish_progress(
                                    f"正在执行工具：{name}...",
                                    preview=final_text or f"调用工具 {name}",
                                    progress=min(90, 30 + len(tool_trace) * 5),
                                    round_index=round_index + 1,
                                )
                                try:
                                    tool_result = execute_tool(session, project_id, name, arguments)
                                    trace_entry: dict[str, Any] = {
                                        "name": name,
                                        "ok": True,
                                        "args": arguments,
                                    }
                                    try:
                                        parsed = json.loads(tool_result)
                                        result_body = (
                                            parsed.get("result") if isinstance(parsed, dict) else None
                                        )
                                        if isinstance(result_body, dict) and result_body.get("task_id"):
                                            trace_entry["result"] = {
                                                "task_id": result_body.get("task_id"),
                                                "task_type": result_body.get("task_type"),
                                            }
                                    except (json.JSONDecodeError, TypeError):
                                        pass
                                    tool_trace.append(trace_entry)
                                except ToolError as exc:
                                    tool_result = json.dumps(
                                        {"ok": False, "error": str(exc)},
                                        ensure_ascii=False,
                                    )
                                    tool_trace.append(
                                        {
                                            "name": name,
                                            "ok": False,
                                            "error": str(exc),
                                            "args": arguments,
                                        }
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

                    # 本轮无工具 → 最终回答
                    if not tool_trace:
                        # 纯聊天：已有 content 则直接用（避免二次请求）
                        final_text = content.strip()
                        if not final_text:
                            last_flush = {"at": 0.0}

                            def on_delta_pure(full_text: str) -> None:
                                raise_if_cancelled()
                                now = time.monotonic()
                                if now - last_flush["at"] < STREAM_FLUSH_INTERVAL_SECONDS:
                                    return
                                last_flush["at"] = now
                                publish_progress(
                                    f"AI 正在回复（已生成 {len(full_text)} 字）...",
                                    preview=full_text,
                                    progress=min(90, 20 + len(full_text) // 50),
                                    round_index=round_index + 1,
                                )

                            final_text = (
                                ai.chat_completion_stream(messages, on_delta=on_delta_pure) or ""
                            ).strip()
                        if not final_text:
                            final_text = "（模型未返回文本）"
                        publish_progress(
                            "AI 正在回复...",
                            preview=final_text,
                            progress=90,
                            round_index=round_index + 1,
                        )
                        break

                    # 有过工具：再流式生成最终回复（不带 tools）
                    last_flush = {"at": 0.0}

                    def on_delta_after_tools(full_text: str) -> None:
                        raise_if_cancelled()
                        now = time.monotonic()
                        if now - last_flush["at"] < STREAM_FLUSH_INTERVAL_SECONDS:
                            return
                        last_flush["at"] = now
                        publish_progress(
                            f"正在整理回复（{len(full_text)} 字）...",
                            preview=full_text,
                            progress=min(95, 80 + len(full_text) // 100),
                            round_index=round_index + 1,
                        )

                    if content.strip():
                        final_text = content.strip()
                        publish_progress(
                            f"已执行 {len(tool_trace)} 次工具，正在整理回复...",
                            preview=final_text,
                            progress=92,
                            round_index=round_index + 1,
                        )
                    else:
                        publish_progress(
                            f"已执行 {len(tool_trace)} 次工具，正在整理回复...",
                            progress=88,
                            round_index=round_index + 1,
                        )
                        final_text = (
                            ai.chat_completion_stream(
                                messages, on_delta=on_delta_after_tools
                            )
                            or ""
                        ).strip()
                    if not final_text:
                        final_text = "已完成相关工具操作。"
                    break
                else:
                    # 超过轮次 — 要求最终总结
                    raise_if_cancelled()
                    messages.append(
                        {
                            "role": "user",
                            "content": "请基于已完成的工具结果，用中文直接给出最终回复，不要再调用工具。",
                        }
                    )
                    last_flush = {"at": 0.0}

                    def on_delta_final(full_text: str) -> None:
                        raise_if_cancelled()
                        now = time.monotonic()
                        if now - last_flush["at"] < STREAM_FLUSH_INTERVAL_SECONDS:
                            return
                        last_flush["at"] = now
                        publish_progress(
                            f"正在整理最终回复（{len(full_text)} 字）...",
                            preview=full_text,
                            progress=95,
                            round_index=MAX_TOOL_ROUNDS,
                        )

                    final_text = (
                        ai.chat_completion_stream(messages, on_delta=on_delta_final) or ""
                    ).strip() or "已达到工具调用上限，请根据已有结果继续。"

            assistant_message.content = final_text
            assistant_message.payload = {
                "streaming": False,
                "tool_calls": tool_trace,
                "tools_enabled": tools_enabled,
                "text_provider": provider_name,
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
            result["tools_enabled"] = tools_enabled
            result["text_provider"] = provider_name
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
                # 取消时尽量保留半成品预览
                if assistant_message and assistant_message.id:
                    msg = session.get(AgentMessage, assistant_message.id)
                    if msg and not (msg.content or "").strip():
                        preview = (task.result or {}).get("stream_preview") or ""
                        msg.content = preview or "（已取消）"
                        msg.payload = {
                            "streaming": False,
                            "cancelled": True,
                            "tool_calls": tool_trace,
                        }
                        session.add(msg)
                        session.commit()
                return

            friendly = format_assistant_error(exc)
            if assistant_message and assistant_message.id:
                msg = session.get(AgentMessage, assistant_message.id)
                if msg:
                    msg.content = msg.content or f"（生成失败）{friendly}"
                    msg.payload = {
                        "streaming": False,
                        "error": friendly,
                        "error_raw": str(exc),
                        "tool_calls": tool_trace,
                    }
                    session.add(msg)

            task.status = "failed"
            task.message = friendly
            result = dict(task.result or {})
            result["tool_calls"] = tool_trace
            result["error"] = friendly
            result["error_raw"] = str(exc)
            task.result = result
            task.updated_at = datetime.utcnow()
            session.add(task)
            session.commit()
