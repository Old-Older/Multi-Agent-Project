"""Central routing layer (design §2.1, §5, §7, D9).

Owner: JIAN Yimin.

Pure code, never calls an LLM. Every call_<agent> tool call, from the
Orchestrator or from a worker re-delegating, in a group or a DM session, goes
through Router.dispatch(). This keeps one code path for limits, state,
file hand-off, HITL routing and statistics.

The Router is also the only writer of the StateTable and the owner of the
per-session boards: as a bus observer it sees every message, updates the task
state from STATUS / TASK_RESULT, wakes up whoever waits for a result or a human
answer, and feeds each message to the board of its session.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from mas.config import Settings
from mas.core.board import SessionBoard
from mas.core.bus import MessageBus
from mas.core.human import CANCELLED_ANSWER, HitlKind
from mas.core.message import GROUP_MAIN, HUMAN, ORCHESTRATOR, Message, MsgType
from mas.core.state import StateTable
from mas.core.task import FailureMode, Task, TaskResult, TaskStatus
from mas.sandbox.base import Sandbox

log = logging.getLogger(__name__)

_LEADING_MENTION = re.compile(r"^\s*@\S+\s*")


def _norm(goal: str) -> str:
    return " ".join(goal.lower().split())


class Router:
    def __init__(self, bus: MessageBus, state: StateTable,
                 sandboxes: dict[str, Sandbox], settings: Settings) -> None:
        """Registers itself as a bus observer to receive TASK_RESULT and
        HITL_RESPONSE messages on every channel."""
        self.bus = bus
        self.state = state
        self.sandboxes = sandboxes
        self.settings = settings
        self._boards: dict[str, SessionBoard] = {}
        self._task_waiters: dict[str, asyncio.Future[TaskResult]] = {}
        self._hitl_waiters: dict[tuple[str, str], asyncio.Future[str]] = {}
        self._hitl_root: dict[tuple[str, str], str] = {}      # open request -> its root id
        self._hitl_counter: dict[str, int] = {}
        self._root_counter = 0
        self._delegations: dict[str, int] = {}                # parent task id -> count
        self._attempts: dict[tuple[str, str, str], list[str]] = {}
        self._cancelled_roots: set[str] = set()
        bus.add_observer(self._on_message)

    # ---- dispatch --------------------------------------------------------

    async def dispatch(self, *, requester: str, target: str, goal: str,
                       context: str = "", files: list[str] | None = None,
                       parent: Task | None = None, session_id: str,
                       root_id: str, origin_channel: str) -> TaskResult:
        """Create a Task, run it on `target`, return its result.

        1. Check limits (depth, cycle in chain, delegations per task, retries of
           the same goal) and find the files. On violation the call is refused: the task
           is still registered, as FAILED with error "refused: ...", so it shows up in
           /status and in the eval statistics, but the target is never contacted and the
           refusal does not count towards the retry or delegation limits.
        2. Register in the StateTable; copy `files` from the requester's sandbox
           (or from the agent that produced them in this root) into the target's inbox/.
        3. Publish TASK_ASSIGN in task.channel (the group, or the DM of requester and target).
        4. Await the TASK_RESULT of that task, with settings.subtask_timeout_s;
           on timeout return a TIMEOUT failure. The clock does not run while the task
           is WAITING_HUMAN (a human may take as long as they like; /cancel ends it).
        Never raises for task failures.
        """
        files = list(files or [])
        chain = (list(parent.chain) if parent else []) + [requester]
        task = Task(goal=goal, assignee=target, requester=requester,
                    session_id=session_id, root_id=root_id,
                    origin_channel=origin_channel, context=context, files=files,
                    chain=chain, parent_id=parent.id if parent else None)

        denied = self._check_limits(requester, target, goal, parent, root_id, chain)
        sources: dict[str, Path] = {}
        if denied is None:
            for name in files:
                src = self.locate_file(name, requester, root_id)
                if src is None:
                    denied = f"file not found: {name}"
                    break
                sources[name] = src
        if denied is not None:
            return self._refuse(task, denied)

        self.state.register(task)
        if parent:
            self._delegations[parent.id] = self._delegations.get(parent.id, 0) + 1
        self._attempts.setdefault((root_id, target, _norm(goal)), []).append(task.id)

        try:
            for name, src in sources.items():
                self.sandboxes[target].import_file(src, Path(name).name)
        except Exception as exc:                      # sandbox I/O problem, not a bug here
            result = TaskResult(task.id, False, "", error=f"cannot hand over files: {exc}",
                                failure_mode=FailureMode.TOOL_ERROR)
            self.state.finish(result)
            return result

        fut: asyncio.Future[TaskResult] = asyncio.get_running_loop().create_future()
        self._task_waiters[task.id] = fut
        await self.bus.publish(Message(
            MsgType.TASK_ASSIGN, sender=requester, channel=task.channel,
            content=f"@{target} {goal}", payload={"task": task.to_dict()},
            receiver=target, mentions=[target]))
        try:
            while True:
                done, _ = await asyncio.wait({fut}, timeout=self.settings.subtask_timeout_s)
                if done:
                    return fut.result()
                if self.state.get(task.id).status == TaskStatus.WAITING_HUMAN:
                    continue                  # a human is thinking: keep waiting
                result = TaskResult(
                    task.id, False, "", error=f"no result within {self.settings.subtask_timeout_s}s",
                    failure_mode=FailureMode.TIMEOUT)
                self.state.finish(result)
                return result
        finally:
            self._task_waiters.pop(task.id, None)

    def _check_limits(self, requester: str, target: str, goal: str, parent: Task | None,
                      root_id: str, chain: list[str]) -> str | None:
        """Return the reason a call must be refused, or None if it may proceed."""
        s = self.settings
        if root_id in self._cancelled_roots:
            return "the request was cancelled"
        if target in (HUMAN, ORCHESTRATOR) or target not in self.bus.members(GROUP_MAIN):
            return f"unknown agent: {target}"
        if target in chain:
            return f"delegation cycle: {' -> '.join(chain + [target])}"
        if len(chain) - 1 > s.max_delegation_depth:
            return f"delegation depth would exceed {s.max_delegation_depth}"
        if parent and self._delegations.get(parent.id, 0) >= s.max_delegations_per_task:
            return f"task {parent.id} already delegated {s.max_delegations_per_task} times"
        tries = self._attempts.get((root_id, target, _norm(goal)), [])
        attempts = sum(1 for tid in tries if self.state.get(tid).status != TaskStatus.DECLINED)
        if attempts > s.max_retries_same_goal:       # first try + max_retries retries
            return f"same goal already tried {attempts} times on {target}"
        return None

    def locate_file(self, name: str, requester: str, root_id: str) -> Path | None:
        """Where `name` lives: the requester's own sandbox, else the workspace of the
        agent whose result in this root listed it as an artifact (newest first). The
        Orchestrator uses it to collect the deliverables."""
        owners = [requester] + [
            t.assignee for t in reversed(self.state.by_root(root_id))
            if (r := self.state.result(t.id)) and name in r.artifacts]
        for owner in owners:
            sb = self.sandboxes.get(owner)
            try:
                if sb and sb.exists(name):
                    return sb.resolve(name)
            except PermissionError:
                return None
        return None

    def _refuse(self, task: Task, reason: str) -> TaskResult:
        """Record a refused call as a FAILED task (for /status and debugging) and return
        its result. Not added to the retry or delegation counters."""
        self.state.register(task)
        result = TaskResult(task.id, False, "", error=f"refused: {reason}",
                            failure_mode=FailureMode.TOOL_ERROR)
        self.state.finish(result)
        return result

    # ---- direct tasks ------------------------------------------------------

    def open_direct_task(self, msg: Message, assignee: str) -> Task:
        """Register a task a human gave directly to an agent (DM, or @agent in
        the group). The returned task's origin_channel is msg.channel."""
        session_id = self.session_of(msg.channel)
        task = Task(goal=_LEADING_MENTION.sub("", msg.content, count=1).strip() or msg.content,
                    assignee=assignee, requester=HUMAN, session_id=session_id,
                    root_id=self.new_root_id(session_id), origin_channel=msg.channel,
                    chain=[HUMAN])
        self.state.register(task)
        self._attempts.setdefault((task.root_id, assignee, _norm(task.goal)), []).append(task.id)
        board = self.board(session_id)
        board.start_root(task.root_id, msg.content)
        board.add_task(task)                 # no TASK_ASSIGN is published for these
        return task

    def new_root_id(self, session_id: str = "") -> str:
        """Next root id: R1, R2, ... Unique across all sessions, because the state table,
        cancel_root and the retry counters identify a root by its id alone. (`session_id`
        is accepted for compatibility and not used.)"""
        self._root_counter += 1
        return f"R{self._root_counter}"

    # ---- human in the loop -----------------------------------------------

    async def request_human(self, *, session_id: str, root_id: str, origin_channel: str,
                            requester: str, kind: HitlKind, question: str,
                            options: list[str] | None = None,
                            task_id: str | None = None) -> str:
        """Publish HITL_REQUEST (@human, numbered h1, h2, ... per session) in
        `origin_channel` and wait for the matching HITL_RESPONSE.

        Workers do not call this directly: Agent.ask_human(task, ...) fills the
        arguments from the task (origin_channel is inherited down the delegation chain,
        so a delegated agent's request still appears where the human started).
        The Orchestrator has no Task when it asks for clarification, so it passes
        task_id=None. With a task_id the task is WAITING_HUMAN meanwhile.
        Returns CANCELLED_ANSWER if the request is cancelled with /cancel."""
        options = list(options or [])
        n = self._hitl_counter.get(session_id, 0) + 1
        self._hitl_counter[session_id] = n
        request_id = f"h{n}"
        key = (session_id, request_id)
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._hitl_waiters[key] = fut
        self._hitl_root[key] = root_id
        if task_id:
            self._set_state(task_id, TaskStatus.WAITING_HUMAN, question)
        text = f"@human {question}" + (f" [{' / '.join(options)}]" if options else "")
        try:
            await self.bus.publish(Message(
                MsgType.HITL_REQUEST, sender=requester, channel=origin_channel,
                content=text, receiver=HUMAN, mentions=[HUMAN],
                payload={"request_id": request_id, "task_id": task_id, "root_id": root_id,
                         "kind": kind.value, "question": question, "options": options}))
            answer = await fut
        finally:
            self._hitl_waiters.pop(key, None)
            self._hitl_root.pop(key, None)
        if task_id:
            self._set_state(task_id, TaskStatus.RUNNING)
        return answer

    # ---- sessions and boards -----------------------------------------------

    def board(self, session_id: str) -> SessionBoard:
        """The session's board (created on first use)."""
        if session_id not in self._boards:
            self._boards[session_id] = SessionBoard(session_id, self.settings.board_max_chars)
        return self._boards[session_id]

    def session_of(self, channel: str) -> str:
        """Session id for a channel: the group chat, or one DM conversation.
        Each channel is its own session, so the channel name is the id."""
        return channel

    # ---- cancel ------------------------------------------------------------

    def cancel_root(self, root_id: str) -> None:
        """/cancel: mark all unfinished tasks of the root CANCELLED and release waiters.
        Later calls in the same root are refused. Agents still running keep going in the
        background, their late results are stored but do not change the status."""
        self._cancelled_roots.add(root_id)
        for task in self.state.by_root(root_id):
            if task.status.finished:
                continue
            self.state.update(task.id, TaskStatus.CANCELLED, "cancelled by human")
            fut = self._task_waiters.pop(task.id, None)
            if fut and not fut.done():
                fut.set_result(TaskResult(task.id, False, "", error="cancelled"))
        for key, root in list(self._hitl_root.items()):      # also the Orchestrator's questions
            waiter = self._hitl_waiters.get(key)
            if root == root_id and waiter and not waiter.done():
                waiter.set_result(CANCELLED_ANSWER)

    def cancel_session(self, session_id: str) -> list[str]:
        """Cancel every root that still has unfinished tasks in the session (for /cancel in
        a DM, where the Orchestrator is not involved). Returns the roots it cancelled."""
        roots = list(dict.fromkeys(t.root_id for t in self.state.active(session_id)))
        for root_id in roots:
            self.cancel_root(root_id)
        return roots

    # ---- bus observer ------------------------------------------------------

    def _on_message(self, msg: Message) -> None:
        try:
            if msg.type == MsgType.STATUS:
                p = msg.payload
                self._set_state(p["task_id"], TaskStatus(p["status"]), p.get("note", ""))
            elif msg.type == MsgType.TASK_RESULT:
                self._on_result(TaskResult.from_dict(msg.payload["result"]))
            elif msg.type == MsgType.HITL_RESPONSE:
                key = (self.session_of(msg.channel), msg.payload["request_id"])
                fut = self._hitl_waiters.get(key)
                if fut and not fut.done():
                    fut.set_result(msg.payload["answer"])
        except Exception:
            log.exception("router failed on message %s", msg.id)
        try:
            self.board(self.session_of(msg.channel)).on_message(msg)
        except Exception:
            log.exception("board failed on message %s", msg.id)

    def _on_result(self, result: TaskResult) -> None:
        try:
            task = self.state.get(result.task_id)
        except KeyError:
            return
        if task.status.finished and task.status != TaskStatus.CANCELLED:
            return                      # late result of a task that already timed out
        self.state.finish(result)
        fut = self._task_waiters.get(result.task_id)
        if fut and not fut.done():
            fut.set_result(result)

    def _set_state(self, task_id: str, status: TaskStatus, note: str = "") -> None:
        """Update a task unless it is unknown or already finished."""
        try:
            if not self.state.get(task_id).status.finished:
                self.state.update(task_id, status, note)
        except KeyError:
            pass
