"""Central routing layer (design §2.1, §5, §7, D9).

Owner: JIAN Yimin.

Pure code, never calls an LLM. Every call_<agent> tool call, from the
Orchestrator or from a worker re-delegating, in a group or a DM session, goes
through Router.dispatch(). This keeps one code path for limits, state,
file hand-off, HITL routing and statistics.
"""
from __future__ import annotations

from mas.config import Settings
from mas.core.board import SessionBoard
from mas.core.bus import MessageBus
from mas.core.human import HitlKind
from mas.core.message import Message
from mas.core.state import StateTable
from mas.core.task import Task, TaskResult
from mas.sandbox.base import Sandbox


class Router:
    def __init__(self, bus: MessageBus, state: StateTable,
                 sandboxes: dict[str, Sandbox], settings: Settings) -> None:
        """Registers itself as a bus observer to receive TASK_RESULT and
        HITL_RESPONSE messages on every channel."""
        self.bus = bus
        self.state = state
        self.sandboxes = sandboxes
        self.settings = settings

    async def dispatch(self, *, requester: str, target: str, goal: str,
                       context: str = "", files: list[str] | None = None,
                       parent: Task | None = None, session_id: str,
                       root_id: str, origin_channel: str) -> TaskResult:
        """Create a Task, run it on `target`, return its result.

        1. Check limits (depth, cycle in chain, delegations per task, retries of
           the same goal). On violation return TaskResult(success=False, error=...)
           without contacting the target.
        2. Register in the StateTable; copy `files` from the requester's sandbox
           into the target's inbox/.
        3. Publish TASK_ASSIGN: in GROUP_MAIN if origin_channel is a group,
           otherwise in dm_channel(requester, target).
        4. Await the TASK_RESULT whose reply_to is that message, with
           settings.subtask_timeout_s; on timeout return a TIMEOUT failure.
        Never raises for task failures.
        """
        raise NotImplementedError

    def open_direct_task(self, msg: Message, assignee: str) -> Task:
        """Register a task a human gave directly to an agent (DM, or @agent in
        the group). The returned task's origin_channel is msg.channel."""
        raise NotImplementedError

    async def request_human(self, task: Task, kind: HitlKind, question: str,
                            options: list[str] | None = None) -> str:
        """Publish HITL_REQUEST (@human, numbered h1, h2, ... per session) in
        task.origin_channel and wait for the matching HITL_RESPONSE. Sets the
        task to WAITING_HUMAN meanwhile. Works for delegated tasks too, because
        origin_channel is inherited down the delegation chain."""
        raise NotImplementedError

    def board(self, session_id: str) -> SessionBoard:
        """The session's board (created on first use)."""
        raise NotImplementedError

    def session_of(self, channel: str) -> str:
        """Session id for a channel: the group chat, or one DM conversation."""
        raise NotImplementedError

    def cancel_root(self, root_id: str) -> None:
        """/cancel: mark all unfinished tasks of the root CANCELLED and release waiters."""
        raise NotImplementedError
