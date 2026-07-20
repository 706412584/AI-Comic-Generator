from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlmodel import Session

from app.models.models import AgentRun, Task


class TaskCancelledError(Exception):
    """在 step 执行过程中检测到任务被取消时抛出，由 AgentRuntime 转为 cancelled 状态。"""


@dataclass
class AgentContext:
    session: Session
    task: Task
    agent_run: AgentRun
    input_payload: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)

    def raise_if_cancelled(self):
        """长循环（如逐章分析）中调用，检测用户取消并中断当前 step。"""
        self.session.refresh(self.task)
        if self.task.status == "cancelled":
            raise TaskCancelledError("任务已被用户取消")


@dataclass(frozen=True)
class AgentStep:
    name: str
    label: str
    progress: int
    handler: Callable[[AgentContext], dict[str, Any] | None]


class BaseAgent:
    name = "base_agent"
    label = "基础 Agent"
    version = "1.0"

    def __init__(self, session: Session):
        self.session = session

    def steps(self) -> list[AgentStep]:
        raise NotImplementedError
