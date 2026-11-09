"""Agent base class (design §3, §5, §7).

Owner: JIAN Yimin. WorkerAgent (LI Heyang) and Orchestrator subclass it.

Subclasses implement handle_task / handle_chat; everything about messages,
routing, status and HITL is done here so the ReAct loop never touches the bus.
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod

from mas.config import Settings
from mas.core.bus import MessageBus
from mas.core.human import HitlKind
from mas.core.message import HUMAN, Message, MsgType
from mas.core.router import Router
from mas.core.task import FailureMode, Task, TaskResult, TaskStatus

log = logging.getLogger(__name__)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:max(limit - 1, 0)] + "…"


class Agent(ABC):
    def __init__(self, agent_id: str, bus: MessageBus, router: Router,
                 settings: Settings) -> None:
        self.agent_id = agent_id
        self.bus = bus
        self.router = router
        self.settings = settings

    async def run(self) -> None:
        """Subscribe and dispatch forever. Each accepted message is handled in
        its own asyncio task so one agent can serve several tasks in parallel.
        If run() is cancelled, the handlers still in flight are cancelled too."""
        inbox = self.bus.subscribe(self.agent_id)
        running: set[asyncio.Task] = set()
        try:
            while True:
                msg = await inbox.get()
                if self.should_handle(msg):
                    handler = asyncio.create_task(self.on_message(msg))
                    running.add(handler)
                    handler.add_done_callback(running.discard)
        finally:
            for handler in list(running):
                handler.cancel()
            await asyncio.gather(*running, return_exceptions=True)

    def should_handle(self, msg: Message) -> bool:
        """True if msg.receiver is this agent or it is @mentioned. Everything
        else is received but ignored (no LLM call)."""
        return msg.sender != self.agent_id and (
            msg.receiver == self.agent_id or self.agent_id in msg.mentions)

    async def on_message(self, msg: Message) -> None:
        """TASK_ASSIGN -> handle_task, then publish TASK_RESULT (reply_to = assign id)
        in the same channel. CHAT from the human -> handle_chat. Other messages are
        ignored. Catches every exception: a bug in handle_task becomes a CRASH
        TaskResult, a bug in handle_chat becomes an error line in the chat, so one
        bug never kills the run."""
        try:
            if msg.type == MsgType.TASK_ASSIGN:
                task = Task.from_dict(msg.payload["task"])
                await self._execute(task, reply_to=msg.id, receiver=msg.sender)
            elif msg.type == MsgType.CHAT and msg.sender == HUMAN:
                await self.handle_chat(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("%s failed on message %s", self.agent_id, msg.id)
            await self.bus.publish(Message(
                MsgType.CHAT, sender=self.agent_id, channel=msg.channel, receiver=HUMAN,
                content=f"@{HUMAN} {self.agent_id} 内部出错：{type(exc).__name__}: {exc}",
                mentions=[HUMAN], reply_to=msg.id))

    async def _execute(self, task: Task, *, reply_to: str, receiver: str) -> TaskResult:
        """Run `task` through handle_task and publish its TASK_RESULT. Never raises
        (except for cancellation of the asyncio task itself)."""
        started = time.monotonic()
        if self.is_cancelled(task):
            result = TaskResult(task.id, False, "", error="cancelled")
        else:
            await self.report_status(task, TaskStatus.RUNNING,
                                     f"收到 {task.id}：{_clip(task.goal, 60)}", public=True)
            try:
                result = await self.handle_task(task)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("%s crashed on task %s", self.agent_id, task.id)
                result = TaskResult(task.id, False, "", error=f"{type(exc).__name__}: {exc}",
                                    failure_mode=FailureMode.CRASH)
        result.task_id = task.id                      # a result always belongs to its task
        result.summary = _clip(result.summary, self.settings.result_summary_max_chars)
        if not result.duration:
            result.duration = time.monotonic() - started
        await self.bus.publish(Message(
            MsgType.TASK_RESULT, sender=self.agent_id, channel=task.channel,
            content=self._result_text(result, receiver), payload={"result": result.to_dict()},
            receiver=receiver, mentions=[receiver], reply_to=reply_to))
        return result

    @staticmethod
    def _result_text(result: TaskResult, receiver: str) -> str:
        """Chat text of a TASK_RESULT, from a template (no LLM)."""
        if result.declined:
            text = f"拒绝：{result.error or result.summary}" + (
                f"，建议 {result.suggest}" if result.suggest else "")
        elif result.success:
            text = f"完成：{result.summary}" + (
                f"（文件：{', '.join(result.artifacts)}）" if result.artifacts else "")
        else:
            text = f"失败：{result.error or result.summary}"
        return f"@{receiver} {text}"

    @abstractmethod
    async def handle_task(self, task: Task) -> TaskResult: ...

    async def handle_chat(self, msg: Message) -> None:
        """A human message addressed to this agent (DM or @mention).

        Default (used by Workers): treat it as a task the human gave directly. The Router
        registers it (a new root), handle_task runs, and the TASK_RESULT goes back to the
        human in the same channel. Slash commands (/status, /cancel, ...) belong to the
        Orchestrator and the CLI and are ignored here. Subclasses override this to do
        something else, e.g. answer a question without opening a task."""
        if msg.content.lstrip().startswith("/"):
            return
        task = self.router.open_direct_task(msg, self.agent_id)
        await self._execute(task, reply_to=msg.id, receiver=HUMAN)

    # ---- services for subclasses --------------------------------------------

    async def report_status(self, task: Task, status: TaskStatus, note: str = "",
                            public: bool = False) -> None:
        """Publish STATUS in the task's channel. The Router updates the state table from
        it. public=True also shows `note` in the chat (use it only for: received, done,
        failed, waiting for human); otherwise the message has no text and stays out of
        the chat. Template text, no LLM."""
        await self.bus.publish(Message(
            MsgType.STATUS, sender=self.agent_id, channel=task.channel,
            content=f"{self.agent_id}：{note}" if public and note else "",
            payload={"task_id": task.id, "status": status.value, "note": note, "public": public}))

    async def ask_human(self, task: Task, question: str, kind: HitlKind,
                        options: list[str] | None = None) -> str:
        """Ask the human on behalf of `task`. Returns the answer, or CANCELLED_ANSWER
        if the request was cancelled: treat that as "stop", never as an approval."""
        return await self.router.request_human(
            session_id=task.session_id, root_id=task.root_id,
            origin_channel=task.origin_channel, requester=task.assignee,
            kind=kind, question=question, options=options, task_id=task.id)

    def is_cancelled(self, task: Task) -> bool:
        """True once /cancel has cancelled this task. Workers must check it before every
        step and before running a tool that needs approval; the Router cannot stop a
        running agent, it can only mark the task and release whoever waits for it."""
        try:
            return self.router.state.get(task.id).status == TaskStatus.CANCELLED
        except KeyError:
            return False

    async def call_agent(self, task: Task, target: str, goal: str,
                         context: str = "", files: list[str] | None = None) -> TaskResult:
        """Re-delegate part of `task` to another agent (handler of call_<agent>)."""
        return await self.router.dispatch(
            requester=self.agent_id, target=target, goal=goal, context=context,
            files=files, parent=task, session_id=task.session_id,
            root_id=task.root_id, origin_channel=task.origin_channel)

    def board_text(self, task: Task) -> str:
        return self.router.board(task.session_id).render(self.settings.board_max_chars)
