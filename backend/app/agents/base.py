from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlmodel import Session

from app.models.models import AgentRun, Task


@dataclass
class AgentContext:
    session: Session
    task: Task
    agent_run: AgentRun
    input_payload: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)


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
