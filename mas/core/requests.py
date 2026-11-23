"""RequestTracker: the bookkeeping of one human request, from arrival to final reply.

Owner: JIAN Yimin.

Not an agent. It does no planning and holds no conversation of its own: the member of the team
who leads a request does that (design D18). It sits on the bus as an observer and handles the
human's group messages that are addressed to nobody:

  /status, /cancel     answered from the state table, no LLM
  a message while a request is running
                       an addition to that request; the session board already records it
                       and the workers read it from there
  any other message    a new request (a "root"): choose its lead, hand it over whole, wait for
                       the lead's result, collect the files, close the root, and post the final
                       reply in the lead's name

Everything evaluation needs to know about a request (success, failure mode, duration, the
deliverables and where they were collected) is recorded here in plain code, never taken from an
LLM's description of itself. See `outcomes`, and the payload of the final reply.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from mas.config import Settings
from mas.core.bus import MessageBus
from mas.core.human import CANCELLED_ANSWER
from mas.core.lead import LeadSelector
from mas.core.message import HUMAN, ORCHESTRATOR, Message, MsgType, is_group
from mas.core.router import Router
from mas.core.task import FailureMode, TaskResult
from mas.llm.base import LLMClient

log = logging.getLogger(__name__)

# The identity the request layer uses for what it says itself (/status, /cancel) and as the
# requester of a lead's task. It is not an agent and is not a member of the chat.
SYSTEM = ORCHESTRATOR


@dataclass
class RootOutcome:
    """How one root ended. The eval harness reads these (also carried in the payload of
    the final reply)."""
    root_id: str
    success: bool                     # True if the lead reported success (a checker decides if it is right)
    rounds: int                       # the lead's ReAct steps
    failure_mode: FailureMode | None
    summary: str
    deliverables: list[str] = field(default_factory=list)
    output_dir: str = ""
    duration: float = 0.0
    lead: str = ""


@dataclass
class _RootRun:
    """A root that is being worked on right now."""
    root_id: str
    session_id: str
    channel: str
    started: float = field(default_factory=time.perf_counter)   # monotonic() ticks every 15.6 ms on Windows
    stamp: str = field(default_factory=lambda: time.strftime("%Y%m%d-%H%M%S"))   # start time, names the output dir
    task: asyncio.Task | None = None                          # the asyncio task running run_request
    rounds: int = 0
    lead: str = ""


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


class RequestTracker:
    def __init__(self, bus: MessageBus, router: Router, settings: Settings,
                 llm: LLMClient, roles: dict) -> None:
        self.bus = bus
        self.router = router
        self.settings = settings
        self.roles = roles
        self.selector = LeadSelector(llm, roles, settings.temperature)
        self.outcomes: dict[str, RootOutcome] = {}
        self._runs: dict[str, _RootRun] = {}              # session id -> the root running there
        self._handlers: set[asyncio.Task] = set()
        bus.add_observer(self._on_message)

    # ---- which messages are mine -------------------------------------------------

    @staticmethod
    def is_request(msg: Message) -> bool:
        """A human message in the group that nobody in particular is meant to handle."""
        return (msg.type == MsgType.CHAT and msg.sender == HUMAN and is_group(msg.channel)
                and msg.receiver in (None, ORCHESTRATOR) and not msg.mentions)

    def _on_message(self, msg: Message) -> None:
        """Bus observer (runs synchronously inside publish): start handling `msg` in its own
        asyncio task, so a long request never blocks the bus."""
        if not self.is_request(msg):
            return
        task = asyncio.get_running_loop().create_task(self._handle_safely(msg))
        self._handlers.add(task)
        task.add_done_callback(self._handlers.discard)

    async def stop(self) -> None:
        """Cancel the requests that are still running."""
        handlers = list(self._handlers)
        for task in handlers:
            task.cancel()
        await asyncio.gather(*handlers, return_exceptions=True)

    async def _handle_safely(self, msg: Message) -> None:
        try:
            await self.handle_chat(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:                          # a bug here must not kill the run
            log.exception("the request layer failed on message %s", msg.id)
            await self._say(msg, f"@{HUMAN} the request could not be handled: {type(exc).__name__}: {exc}")

    # ---- human messages -----------------------------------------------------------

    async def handle_chat(self, msg: Message) -> None:
        text = msg.content.strip()
        session = self.router.session_of(msg.channel)
        if text.startswith("/"):
            command = text.split(" ")[0].lower()
            if command == "/status":
                await self._say(msg, self.status_text(session))
            elif command == "/cancel":
                await self._cancel(msg, session)
            return                                    # other commands are the CLI's business
        if session in self._runs:                     # a request is running: this is an addition
            return                                    # (the board has recorded it; the workers read it there)
        await self.run_request(msg, self._begin(msg, session))

    def _begin(self, msg: Message, session: str) -> _RootRun:
        """Open a root for `msg`. Synchronous on purpose: no other message can start a
        second root in between the check in handle_chat and this registration."""
        run = _RootRun(root_id=self.router.new_root_id(session), session_id=session, channel=msg.channel)
        self._runs[session] = run
        self.router.start_clock(run.root_id)
        self.router.board(session).start_root(run.root_id, msg.content)
        return run

    async def _say(self, msg: Message, text: str, payload: dict | None = None, sender: str = SYSTEM) -> None:
        await self.bus.publish(Message(
            MsgType.CHAT, sender=sender, channel=msg.channel, content=text,
            receiver=HUMAN, mentions=[HUMAN] if text.startswith("@") else [],
            reply_to=msg.id, payload=payload or {}))

    def status_text(self, session: str) -> str:
        """Answer to /status, from the state table, no LLM. A root that is running but has
        not sent anything out yet is mentioned too."""
        text = self.router.state.status_text(session)
        run = self._runs.get(session)
        if run and not self.router.state.by_root(run.root_id):
            line = f"{run.root_id} is being worked on; no task has been sent out yet."
            return line if text.startswith("No tasks in this session") else f"{line}\n{text}"
        return text

    async def _cancel(self, msg: Message, session: str) -> None:
        """/cancel: cancel the running root and every other unfinished task of the session
        (e.g. direct tasks), then say what was cancelled."""
        run = self._runs.get(session)
        roots = self.router.cancel_session(session)
        if run is not None:
            self.router.cancel_root(run.root_id)      # also refuses its further calls
            if run.root_id not in roots:
                roots.append(run.root_id)
            if run.task is not None and run.task is not asyncio.current_task():
                run.task.cancel()
        await self._say(msg, f"Cancelled {', '.join(roots)}" if roots else "No unfinished task to cancel",
                        payload={"cancelled_roots": roots})

    # ---- one request ---------------------------------------------------------------

    async def run_request(self, msg: Message, run: _RootRun | None = None) -> None:
        """One human request: choose the lead (cached, with a fallback), hand it the request
        whole and wait for its result, then close the root and reply."""
        session = self.router.session_of(msg.channel)
        run = run or self._begin(msg, session)
        run.task = asyncio.current_task()
        board = self.router.board(session)
        try:
            run.lead = await self.selector.choose(session, msg.content)
            board.set_plan(run.root_id, f"{run.lead} leads this request")
            result = await self.router.dispatch(
                requester=SYSTEM, target=run.lead, goal=msg.content.strip(), parent=None,
                session_id=session, root_id=run.root_id, origin_channel=msg.channel,
                timeout=self.settings.lead_timeout_s)
            run.rounds = result.steps
            await self._conclude(msg, run, result)
        except asyncio.CancelledError:
            self._close(run, False, None, "Cancelled", [])
            raise
        except Exception as exc:
            # A scenario driver waits for a final message before it posts the next task.
            log.exception("request %s failed", run.root_id)
            summary = f"the request could not be handled: {type(exc).__name__}: {exc}"
            self._close(run, False, FailureMode.CRASH, summary, [])
            await self._say(msg, f"@{HUMAN} {summary}", payload={
                "final": True, "root_id": run.root_id, "success": False,
                "failure_mode": FailureMode.CRASH.value, "deliverables": []})
        finally:
            self._runs.pop(session, None)
            if not board.roots[run.root_id].finished:         # a bug ended the request: do not leave it open
                self._close(run, False, FailureMode.CRASH, "Internal error, the request was interrupted", [])

    def _close(self, run: _RootRun, success: bool, failure: FailureMode | None, summary: str,
               deliverables: list[str], output_dir: str = "") -> RootOutcome:
        """Record how the root ended and close it on the board."""
        outcome = RootOutcome(run.root_id, success, run.rounds, failure, summary, deliverables,
                              output_dir, time.perf_counter() - run.started, run.lead)
        self.outcomes[run.root_id] = outcome
        self.router.board(run.session_id).finish_root(run.root_id, summary, deliverables)
        return outcome

    async def _conclude(self, msg: Message, run: _RootRun, result: TaskResult) -> None:
        """Collect the deliverables, close the root and post the lead's final reply."""
        if result.error == CANCELLED_ANSWER and self.router.root_cancelled(run.root_id):
            # /cancel already told the human. A worker can also return the word
            # "cancelled" on its own, in which case the scenario still needs a reply.
            self._close(run, False, None, "Cancelled", [])
            return
        out_dir = self._output_dir(run)
        copied, missing = self._collect(run, result, out_dir)
        failure = None if result.success else (result.failure_mode or FailureMode.TOOL_ERROR)
        summary = result.summary.strip() or result.error or ("(done)" if result.success else "(failed)")
        if not result.success and result.error and result.summary.strip() and result.error not in summary:
            summary = f"{summary}\n({result.error})"
        outcome = self._close(run, result.success, failure, summary, copied, str(out_dir) if copied else "")
        text = f"@{HUMAN} {summary}"
        if copied:
            text += f"\nDeliverables: {', '.join(copied)} (collected in {out_dir})"
        if missing:
            text += f"\n(files not found: {', '.join(missing)})"
        await self._say(msg, text, sender=run.lead, payload={
            "final": True, "root_id": run.root_id, "success": outcome.success, "rounds": outcome.rounds,
            "failure_mode": failure.value if failure else None, "deliverables": copied,
            "output_dir": outcome.output_dir, "lead": run.lead, "duration": outcome.duration})

    def _collect(self, run: _RootRun, result: TaskResult, out_dir: Path) -> tuple[list[str], list[str]]:
        """Copy the deliverables into out_dir. They are the files the lead listed; if it listed
        none, every file the successful tasks of the root wrote. Each file comes from the
        workspace of the agent that wrote it; a listed file that the lead and a teammate both
        have comes from whoever revised it last (Router.delivery_owner)."""
        listed = list(dict.fromkeys(result.artifacts))
        if listed:
            pairs = [(self.router.delivery_owner(run.root_id, run.lead, name), name) for name in listed]
        else:
            pairs = self.router.root_artifacts(run.root_id)                    # (agent, file)
        copied, missing, used = [], [], set()
        for agent, name in pairs:
            sandbox = self.router.sandboxes.get(agent)
            try:
                found = sandbox is not None and sandbox.exists(name)
            except PermissionError:
                found = False
            if not found:
                missing.append(name)
                continue
            target = Path(name).name
            if target in used:                                  # two agents wrote a file of that name
                target = f"{agent}_{target}"
            used.add(target)
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sandbox.resolve(name), out_dir / target)
            copied.append(target)
        return copied, missing

    def _output_dir(self, run: _RootRun) -> Path:
        """data/output/<root>-<start time>/. Root ids start again from R1 in every program
        run, the start time keeps the runs apart (and a counter keeps two runs that started
        in the same second apart)."""
        base = self.settings.output_dir / f"{run.root_id}-{run.stamp}"
        path, n = base, 1
        while path.exists():
            n += 1
            path = base.with_name(f"{base.name}-{n}")
        return path
