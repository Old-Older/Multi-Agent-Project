"""Agent base class (design §3, §5, §7).

Owner: JIAN Yimin. WorkerAgent (LI Heyang) and Orchestrator subclass it.

Subclasses implement handle_task / handle_chat; everything about messages,
routing, status and HITL is done here so the ReAct loop never touches the bus.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from mas.config import Settings
from mas.core.bus import MessageBus
from mas.core.human import HitlKind
from mas.core.message import Message
from mas.core.router import Router
from mas.core.task import Task, TaskResult, TaskStatus


class Agent(ABC):
    def __init__(self, agent_id: str, bus: MessageBus, router: Router,
                 settings: Settings) -> None:
        self.agent_id = agent_id
        self.bus = bus
        self.router = router
        self.settings = settings

    async def run(self) -> None:
        """Subscribe and dispatch forever. Each accepted message is handled in
        its own asyncio task so one agent can serve several tasks in parallel."""
        raise NotImplementedError

    def should_handle(self, msg: Message) -> bool:
        """True if msg.receiver is this agent or it is @mentioned. Everything
        else is received but ignored (no LLM call)."""
        return msg.sender != self.agent_id and (
            msg.receiver == self.agent_id or self.agent_id in msg.mentions)

    async def on_message(self, msg: Message) -> None:
        """TASK_ASSIGN -> handle_task, then publish TASK_RESULT (reply_to = assign id)
        in the same channel. CHAT -> handle_chat. Catches every exception and turns
        it into a CRASH TaskResult so one bug never kills the run."""
        raise NotImplementedError

    @abstractmethod
    async def handle_task(self, task: Task) -> TaskResult: ...

    async def handle_chat(self, msg: Message) -> None:
        """A human message addressed to this agent (DM or @mention)."""
        raise NotImplementedError

    # ---- services for subclasses --------------------------------------------

    async def report_status(self, task: Task, status: TaskStatus, note: str = "",
                            public: bool = False) -> None:
        """Publish STATUS. public=True also shows it in the chat (only for:
        received, done, failed, waiting for human). Template text, no LLM."""
        raise NotImplementedError

    async def ask_human(self, task: Task, question: str, kind: HitlKind,
                        options: list[str] | None = None) -> str:
        return await self.router.request_human(task, kind, question, options)

    async def call_agent(self, task: Task, target: str, goal: str,
                         context: str = "", files: list[str] | None = None) -> TaskResult:
        """Re-delegate part of `task` to another agent (handler of call_<agent>)."""
        return await self.router.dispatch(
            requester=self.agent_id, target=target, goal=goal, context=context,
            files=files, parent=task, session_id=task.session_id,
            root_id=task.root_id, origin_channel=task.origin_channel)

    def board_text(self, task: Task) -> str:
        return self.router.board(task.session_id).render(self.settings.board_max_chars)
