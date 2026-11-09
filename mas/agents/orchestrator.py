"""Orchestrator: agent-as-a-tool ReAct loop (design §2, D1, D3–D6).

Owner: JIAN Yimin.

One human request = one root. run_root() asks the LLM what to do, runs the
call_<agent> tool calls it returns (several in one round run in parallel),
feeds the results back, and stops when the LLM calls finish() or the rounds
run out. Everything around the LLM (routing, limits, state, /status, /cancel)
is plain code.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from mas.agents.base import Agent
from mas.agents.roles import RoleConfig
from mas.agents.virtual_tools import (ASK_HUMAN, ASK_HUMAN_SPEC, FINISH, FINISH_SPEC,
                                      call_agent_spec, target_of)
from mas.config import Settings
from mas.core.bus import MessageBus
from mas.core.human import CANCELLED_ANSWER, HitlKind
from mas.core.message import HUMAN, ORCHESTRATOR, Message, MsgType, is_group
from mas.core.router import Router
from mas.core.task import FailureMode, Task, TaskResult
from mas.llm.base import ChatMessage, FunctionSpec, LLMClient, LLMError, ToolCall
from mas.memory.base import Memory

log = logging.getLogger(__name__)


@dataclass
class RootOutcome:
    """How one root ended. The eval harness reads these (also carried in the payload of
    the final reply)."""
    root_id: str
    success: bool                     # True if the LLM called finish (the checker decides if it is right)
    rounds: int
    failure_mode: FailureMode | None
    summary: str
    deliverables: list[str] = field(default_factory=list)
    output_dir: str = ""
    duration: float = 0.0


@dataclass
class _RootRun:
    """A root that is being worked on right now."""
    root_id: str
    session_id: str
    channel: str
    started: float = field(default_factory=time.monotonic)
    task: asyncio.Task | None = None                          # the asyncio task running run_root
    interjections: list[str] = field(default_factory=list)    # human additions not yet shown to the LLM
    results: list[tuple[str, str, TaskResult]] = field(default_factory=list)   # (agent, goal, result)
    rounds: int = 0

    def drain(self) -> list[str]:
        out, self.interjections = self.interjections, []
        return out


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


class Orchestrator(Agent):
    def __init__(self, bus: MessageBus, router: Router, settings: Settings,
                 llm: LLMClient, roles: dict[str, RoleConfig],
                 memories: dict[str, Memory]) -> None:
        super().__init__(ORCHESTRATOR, bus, router, settings)
        self.llm = llm
        self.roles = roles
        self.memories = memories      # read-only, for capability profiles
        self.outcomes: dict[str, RootOutcome] = {}
        self._runs: dict[str, _RootRun] = {}      # session id -> the root running there

    # ---- which messages are mine ---------------------------------------------

    def should_handle(self, msg: Message) -> bool:
        """Also handles human group messages that @mention nobody (D7 rule 2)."""
        if super().should_handle(msg):
            return True
        return (msg.type == MsgType.CHAT and msg.sender == HUMAN and is_group(msg.channel)
                and msg.receiver is None and not msg.mentions)

    # ---- human messages ---------------------------------------------------------

    async def handle_chat(self, msg: Message) -> None:
        """/status -> state table text; /cancel -> cancel what is running;
        interjection while a root runs -> append to the running loop;
        otherwise -> run_root(msg)."""
        text = msg.content.strip()
        session = self.router.session_of(msg.channel)
        if text.startswith("/"):
            command = text.split(" ")[0].lower()
            if command == "/status":
                await self._say(msg, self.status_text(session))
            elif command == "/cancel":
                await self._cancel(msg, session)
            return                                    # other commands are the CLI's business
        run = self._runs.get(session)
        if run is not None:                           # a root is already running: this is an addition
            run.interjections.append(text)
            return
        await self.run_root(msg, self._begin(msg, session))

    def _begin(self, msg: Message, session: str) -> _RootRun:
        """Open a root for `msg`. Synchronous on purpose: no other message can start a
        second root in between the check in handle_chat and this registration."""
        run = _RootRun(root_id=self.router.new_root_id(session), session_id=session, channel=msg.channel)
        self._runs[session] = run
        self.router.board(session).start_root(run.root_id, msg.content)
        return run

    async def _say(self, msg: Message, text: str, payload: dict | None = None) -> None:
        await self.bus.publish(Message(
            MsgType.CHAT, sender=ORCHESTRATOR, channel=msg.channel, content=text,
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
        await self.announce_cancelled(msg.channel, roots, msg.id)

    # ---- one request ---------------------------------------------------------------

    async def run_root(self, msg: Message, run: _RootRun | None = None) -> None:
        """One human request.

        up to settings.max_orchestrator_rounds:
          resp = llm.chat(messages, function_specs(session))
          resp.text -> board.set_plan (the "Remaining steps" line)
          run all call_<agent> tool calls concurrently (asyncio.gather) via
            router.dispatch; feed back summary + artifacts + success only
          ask_human -> router.request_human(HitlKind.CLARIFY)
          finish -> board.finish_root, copy deliverables to output/<root_id>/,
            post the final reply in msg.channel
        When rounds run out, report what is done (MAX_ROUNDS).
        """
        session = self.router.session_of(msg.channel)
        run = run or self._begin(msg, session)
        run.task = asyncio.current_task()
        board = self.router.board(session)
        try:
            await self._loop(msg, run)
        except asyncio.CancelledError:
            self._close(run, False, None, "Cancelled", [])
            raise
        finally:
            self._runs.pop(session, None)
            if not board.roots[run.root_id].finished:         # a bug ended the loop: do not leave it open
                self._close(run, False, FailureMode.CRASH, "Internal error, the request was interrupted", [])

    def _close(self, run: _RootRun, success: bool, failure: FailureMode | None, summary: str,
               deliverables: list[str], output_dir: str = "") -> RootOutcome:
        """Record how the root ended and close it on the board."""
        outcome = RootOutcome(run.root_id, success, run.rounds, failure, summary, deliverables,
                              output_dir, time.monotonic() - run.started)
        self.outcomes[run.root_id] = outcome
        self.router.board(run.session_id).finish_root(run.root_id, summary, deliverables)
        return outcome

    async def _loop(self, msg: Message, run: _RootRun) -> None:
        board = self.router.board(run.session_id)
        specs = self.function_specs(run.session_id)          # capability profiles refreshed per root
        messages: list[ChatMessage] = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": f"Human request: {msg.content.strip()}\n\n{board.render()}"},
        ]
        for n in range(1, self.settings.max_orchestrator_rounds + 1):
            run.rounds = n
            for text in run.drain():
                messages.append({"role": "user", "content": f"(Human addition) {text}"})
            try:
                resp = await self.llm.chat(list(messages), specs, temperature=self.settings.temperature)
            except LLMError as exc:
                await self._conclude(msg, run, False, FailureMode.CRASH, f"LLM call failed: {exc}",
                                     self._artifacts(run))
                return
            if resp.text.strip():
                board.set_plan(run.root_id, _clip(resp.text, 200))
            if not resp.tool_calls:
                if resp.text.strip():                        # the answer without the finish tool: accept it
                    await self._conclude(msg, run, True, None, resp.text.strip(), self._artifacts(run))
                    return
                messages.append({"role": "user", "content": "Please call a tool; when the task is done, call finish."})
                continue
            messages.append(self._assistant_message(resp.text, resp.tool_calls))
            observations, finish = await self._run_tools(msg, run, resp.tool_calls)
            for tc in resp.tool_calls:
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": observations[tc.id]})
            if finish is not None:
                args = finish.arguments
                await self._conclude(msg, run, True, None, str(args.get("summary") or "").strip() or "(done)",
                                     [str(d) for d in args.get("deliverables") or []])
                return
        await self._conclude(msg, run, False, FailureMode.MAX_ROUNDS, self._partial_summary(run),
                             self._artifacts(run))

    # ---- tools ---------------------------------------------------------------------

    async def _run_tools(self, msg: Message, run: _RootRun, calls: list[ToolCall]
                         ) -> tuple[dict[str, str], ToolCall | None]:
        """Run one round of tool calls. Returns the observation text of every call (by id)
        and the finish call if it is to be honoured."""
        obs: dict[str, str] = {}
        agents = [tc for tc in calls if target_of(tc.name)]
        asks = [tc for tc in calls if tc.name == ASK_HUMAN]
        finishes = [tc for tc in calls if tc.name == FINISH]
        for tc in calls:
            if tc not in agents and tc not in asks and tc not in finishes:
                obs[tc.id] = self._error(f"no such tool: {tc.name}")
        outs = await asyncio.gather(*(self._call_agent(msg, run, tc) for tc in agents))   # in parallel
        obs.update({tc.id: out for tc, out in zip(agents, outs)})
        for tc in asks:                                      # a human answers one at a time
            obs[tc.id] = await self._ask_human(msg, run, tc)
        finish = None
        for tc in finishes:
            if len(calls) > len(finishes) or finish is not None:
                obs[tc.id] = self._error("finish must be called alone: wait for the results of the other calls, and call finish once you have confirmed everything is done.")
            else:
                finish = tc
                obs[tc.id] = json.dumps({"success": True})
        return obs, finish

    async def _call_agent(self, msg: Message, run: _RootRun, tc: ToolCall) -> str:
        target, args = target_of(tc.name), tc.arguments
        goal = str(args.get("goal") or "").strip()
        if target not in self.roles:
            return self._error(f"no such agent: {target}")
        if not goal:
            return self._error("missing argument goal")
        files = args.get("files") or []
        result = await self.router.dispatch(
            requester=ORCHESTRATOR, target=target, goal=goal, context=str(args.get("context") or ""),
            files=[str(f) for f in files] if isinstance(files, list) else [], parent=None,
            session_id=run.session_id, root_id=run.root_id, origin_channel=msg.channel)
        run.results.append((target, goal, result))
        return self._observation(result)

    async def _ask_human(self, msg: Message, run: _RootRun, tc: ToolCall) -> str:
        question = str(tc.arguments.get("question") or "").strip()
        if not question:
            return self._error("missing argument question")
        options = tc.arguments.get("options") or []
        answer = await self.router.request_human(
            session_id=run.session_id, root_id=run.root_id, origin_channel=msg.channel,
            requester=ORCHESTRATOR, kind=HitlKind.CLARIFY, question=question,
            options=[str(o) for o in options] if isinstance(options, list) else [])
        return json.dumps({"answer": answer, **({"cancelled": True} if answer == CANCELLED_ANSWER else {})},
                          ensure_ascii=False)

    @staticmethod
    def _error(text: str) -> str:
        return json.dumps({"success": False, "error": text}, ensure_ascii=False)

    @staticmethod
    def _observation(r: TaskResult) -> str:
        """What the LLM sees of a result: success, summary, artifacts, refs. Never the full text."""
        d: dict[str, object] = {"success": r.success}
        if r.declined:
            d.update(declined=True, reason=r.error or r.summary)
            if r.suggest:
                d["suggest"] = r.suggest
        else:
            for key, value in (("summary", r.summary), ("artifacts", r.artifacts), ("refs", r.refs),
                               ("open_issues", r.open_issues), ("error", r.error)):
                if value:
                    d[key] = value
        return json.dumps(d, ensure_ascii=False)

    @staticmethod
    def _assistant_message(text: str, calls: list[ToolCall]) -> ChatMessage:
        return {"role": "assistant", "content": text or None, "tool_calls": [
            {"id": tc.id, "type": "function", "function": {
                "name": tc.name,
                "arguments": tc.raw_arguments or json.dumps(tc.arguments, ensure_ascii=False)}}
            for tc in calls]}

    # ---- ending ----------------------------------------------------------------------

    def _artifacts(self, run: _RootRun) -> list[str]:
        """Files written by the sub-tasks that succeeded (the partial result)."""
        return list(dict.fromkeys(a for _, _, r in run.results if r.success for a in r.artifacts))

    @staticmethod
    def _partial_summary(run: _RootRun) -> str:
        done = [f"{agent} \"{_clip(goal, 40)}\": {_clip(r.summary, 80)}" for agent, goal, r in run.results if r.success]
        todo = [f"{agent} \"{_clip(goal, 40)}\": {_clip(r.error or r.summary, 80)}"
                for agent, goal, r in run.results if not r.success]
        text = f"Used all {run.rounds} rounds without completing the whole request."
        if done:
            text += " Done: " + "; ".join(done) + "."
        if todo:
            text += " Not done: " + "; ".join(todo) + "."
        return text

    async def _conclude(self, msg: Message, run: _RootRun, success: bool, failure: FailureMode | None,
                        summary: str, deliverables: list[str]) -> None:
        """Copy the deliverables to output/<root_id>/, close the root on the board, and post
        the final reply."""
        out_dir = self.settings.output_dir / run.root_id
        copied, missing = [], []
        for name in dict.fromkeys(deliverables):
            src = self.router.locate_file(name, ORCHESTRATOR, run.root_id)
            if src is None:
                missing.append(name)
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out_dir / Path(name).name)
            copied.append(name)
        outcome = self._close(run, success, failure, summary, copied, str(out_dir) if copied else "")
        text = f"@{HUMAN} {summary}"
        if copied:
            text += f"\nDeliverables: {', '.join(copied)} (collected in {out_dir})"
        if missing:
            text += f"\n(files not found: {', '.join(missing)})"
        await self._say(msg, text, payload={
            "final": True, "root_id": run.root_id, "success": outcome.success, "rounds": outcome.rounds,
            "failure_mode": failure.value if failure else None, "deliverables": copied,
            "output_dir": outcome.output_dir})

    # ---- what the LLM sees -------------------------------------------------------------

    def function_specs(self, session_id: str) -> list[FunctionSpec]:
        """call_<agent> for every role with its memory profile, + ask_human + finish."""
        specs = [call_agent_spec(role, self._profile(role.agent_id)) for role in self.roles.values()]
        return specs + [ASK_HUMAN_SPEC, FINISH_SPEC]

    def _profile(self, agent_id: str) -> str:
        """The agent's capability profile (D5). Only a hint: if memory has none, or fails,
        the tool is described without it."""
        memory = self.memories.get(agent_id)
        if memory is None:
            return ""
        try:
            return memory.profile(self.settings.profile_max_chars)
        except Exception:
            log.exception("could not read the profile of %s", agent_id)
            return ""

    def system_prompt(self) -> str:
        names = ", ".join(f"{r.display_name} (call_{r.agent_id})" for r in self.roles.values())
        return f"""You are the Orchestrator of a multi-agent system. A human makes a request; you hand it to the right agents by calling tools, and report to the human at the end. Your agents: {names}. The description of each tool says what that agent can and cannot do, and how it has performed recently.

Rules:
1. Each call goes to one agent only, and its goal must be something that agent can complete on its own with its own abilities. If several abilities are needed, split the work into several calls; never give one agent a job that needs two agents.
2. Calls that do not depend on each other go in the same round, and they run in parallel. Calls that depend on earlier results go in later rounds.
3. Hand the files produced by an earlier step to the next agent with the files argument; do not repeat their content in context. The overall progress of the session is already on the session board, so context only holds notes specific to this call.
4. Whenever you make tool calls, write one line "Remaining steps: ..." in the text part of the same reply.
5. A tool returns a summary, the artifact file names and whether it succeeded, not the full text. When an agent declines (declined) and gives a suggest, reassign the job to the suggested agent. When a call fails you may rewrite the goal, pick another agent or retry; the same goal is tried at most 3 times, and if it still fails say so honestly in your report.
6. Use ask_human only when the request is too vague to start; if you can reasonably infer what is meant, just do it.
7. Deliverables may only be .md, .txt or code files.
8. When everything is done, call finish at once and alone (not together with other calls); the summary says what was done and deliverables lists the delivered file names. No extra confirmation rounds.
9. A message marked "(Human addition)" is something the human added while you were working; adjust accordingly."""

    async def handle_task(self, task: Task) -> TaskResult:
        raise NotImplementedError("the Orchestrator is never assigned tasks")
