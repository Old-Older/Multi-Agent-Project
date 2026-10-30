"""Human side of the bus (design §7, D12).

HumanIO base and CliHumanIO: JIAN Yimin. AutoResponder: LI Heyang.

The human is a bus participant with id HUMAN. Switching between an
interactive CLI and unattended evaluation is a config change only.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from mas.core.bus import MessageBus
from mas.core.message import HUMAN, Message


class HitlKind(str, Enum):
    APPROVAL = "approval"   # before a requires_approval tool (delete, git push)
    CLARIFY = "clarify"     # task description is ambiguous
    ADVICE = "advice"       # same tool failed twice in a row


@dataclass
class HitlRequest:
    request_id: str         # "h1", "h2", ... unique within a session
    agent_id: str
    task_id: str
    channel: str            # the task's origin_channel
    kind: HitlKind
    question: str
    options: list[str] = field(default_factory=list)


class HumanIO(ABC):
    agent_id = HUMAN

    @abstractmethod
    async def run(self, bus: MessageBus) -> None:
        """Main loop: show incoming messages, answer HITL requests, send human input."""

    @abstractmethod
    async def show(self, msg: Message) -> None: ...

    @abstractmethod
    async def answer(self, req: HitlRequest) -> str:
        """Return the human's answer to a HITL request."""


class CliHumanIO(HumanIO):
    """Terminal UI. Commands: /dm <agent> <text>, /status, /cancel, /reply <hid> <answer>."""

    async def run(self, bus: MessageBus) -> None:
        raise NotImplementedError

    async def show(self, msg: Message) -> None:
        raise NotImplementedError

    async def answer(self, req: HitlRequest) -> str:
        raise NotImplementedError


class AutoResponder(HumanIO):
    """Unattended mode for evaluation: answers every HITL request immediately."""

    DEFAULT_ANSWERS = {
        HitlKind.APPROVAL: "yes",
        HitlKind.CLARIFY: "按原描述执行",
        HitlKind.ADVICE: "换一种方法",
    }

    def __init__(self) -> None:
        self.hitl_count = 0

    async def run(self, bus: MessageBus) -> None:
        raise NotImplementedError

    async def show(self, msg: Message) -> None:
        raise NotImplementedError

    async def answer(self, req: HitlRequest) -> str:
        raise NotImplementedError

    async def submit(self, bus: MessageBus, text: str, channel: str) -> str:
        """Post a task as the human (used by the eval harness); returns the message id."""
        raise NotImplementedError
