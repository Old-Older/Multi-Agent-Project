"""Central routing layer (design §2.1, §5, §7, D9).

Owner: JIAN Yimin.

Pure code, never calls an LLM. Every call_<agent> tool call, from the
request layer or from a worker re-delegating, in a group or a DM session, goes
through Router.dispatch(). This keeps one code path for limits, state,
file hand-off, HITL routing and statistics.

The Router is also the only writer of the StateTable and the owner of the
per-session boards: as a bus observer it sees every message, updates the task
state from STATUS / TASK_RESULT, wakes up whoever waits for a result or a human
answer, and feeds each message to the board of its session.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from mas.config import Settings
from mas.core.board import SessionBoard
from mas.core.bus import MessageBus
from mas.core.human import CANCELLED_ANSWER, HitlKind
from mas.core.message import GROUP_MAIN, HUMAN, ORCHESTRATOR, Message, MsgType
from mas.core.state import StateTable
from mas.core.task import FailureMode, Task, TaskResult, TaskStatus
from mas.sandbox.base import INBOX, Sandbox

log = logging.getLogger(__name__)

_LEADING_MENTION = re.compile(r"^\s*@\S+\s*")
# A word that is a file name: what a goal says about a file it wants the teammate to work on.
# What a reviewer's answer says. Only the answer to a task whose goal asks for a review or a check counts, and an
# upper-case FAIL / REJECT / APPROVE WITH CHANGES is a failing verdict even if some points passed.
_REVIEW_GOAL = re.compile(r"review|check|verif|sign-?off|approv|audit|confirm|复核|復核|審閱|审阅|审核|審核|检查|檢查|核对|核對|验证|驗證",
                          re.IGNORECASE)
_FAIL_UPPER = re.compile(r"\bFAIL(?:ED)?\b|APPROVE WITH CHANGES|NOT APPROVED|\bREJECT(?:ED)?\b")
_FAIL_PHRASE = re.compile(r"approv\w* with (?:conditions?|changes|reservations?)|conditional(?:ly)? approv|not (?:yet )?"
                          r"(?:approved|publishable|ready to (?:send|publish))|不通[過过]|未通[過过]|有條件|有条件", re.IGNORECASE)
_PASS = re.compile(r"\bPASS(?:ED)?\b|\bLGTM\b|\bapproved?\b(?! with)|(?<![不未])通[過过]", re.IGNORECASE)
_FAIL_WEAK = re.compile(r"must[- ]fix|requires? (?:the )?(?:following )?(?:changes|fixes)|[須须]修改|需要修改|top \d+ fixes",
                        re.IGNORECASE)
# A task that asks for a review: the verb is among the first words of its goal ("Re-check ...", "Final consistency check ...",
# "Re-run the consistency check ..."), unless the goal opens with work to be done ("Write a short review of ...").
_REVIEW_VERB = re.compile(
    r"^\W*(?!(?:write|draft|produce|create|build|prepare|compile|update|add|fix|revise|rewrite|make|generate|research|find"
    r"|summari[sz]e|analy[sz]e|apply|implement)\b)(?:\w+\W+){0,4}?(?:review|re-?check|check|verify|confirm|audit|sign-?off|approve)",
    re.IGNORECASE)
_SCRIPT_SUFFIXES = (".py", ".sh", ".pyc")                   # code: needs no reviewer; a helper stays behind first
_FILE_NAME = re.compile(r"(?<![\w/.-])[\w][\w.-]*\.(?:md|txt|py|json|html?|csv|tsv|pdf|docx?|xlsx?|pptx?|js|css|ipynb|ya?ml)\b",
                        re.IGNORECASE)


def _digest(path: Path) -> str | None:
    """A fingerprint of a file's content now (None when it cannot be read)."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _norm(goal: str) -> str:
    return " ".join(goal.lower().split())


@dataclass
class _DispatchBudget:
    """Execution deadline, extended only by actual WAITING_HUMAN intervals."""
    deadline: float
    changed: asyncio.Future[None]
    waiting_since: float | None = None

    def set_waiting(self, waiting: bool, now: float) -> None:
        if waiting == (self.waiting_since is not None):
            return
        if waiting:
            self.waiting_since = now
        else:
            assert self.waiting_since is not None
            self.deadline += now - self.waiting_since
            self.waiting_since = None
        if not self.changed.done():
            self.changed.set_result(None)


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
        self._task_budgets: dict[str, _DispatchBudget] = {}
        self._hitl_waiters: dict[tuple[str, str], asyncio.Future[str]] = {}
        self._hitl_root: dict[tuple[str, str], str] = {}      # open request -> its root id
        self._hitl_counter: dict[str, int] = {}
        self._root_counter = 0
        self._delegations: dict[str, int] = {}                # parent task id -> count
        self._attempts: dict[tuple[str, str, str], list[str]] = {}
        self._cancelled_roots: set[str] = set()
        self._requirements: dict[str, list[str]] = {}         # root id -> what the request explicitly requires
        self._root_extra: dict[str, float] = {}               # root id -> seconds added to its budget for re-checks
        self._root_grants: dict[str, int] = {}
        self._handed: dict[str, dict[str, tuple[Path, str | None]]] = {}   # task id -> file -> (source, fingerprint)
        self.clock = time.monotonic                           # replaceable in tests
        self._root_started: dict[str, float] = {}             # root id -> when its time budget began
        self._root_human_wait: dict[str, float] = {}          # root id -> seconds spent waiting for the human
        bus.add_observer(self._on_message)

    # ---- dispatch --------------------------------------------------------

    async def dispatch(self, *, requester: str, target: str, goal: str,
                       context: str = "", files: list[str] | None = None,
                       parent: Task | None = None, session_id: str,
                       root_id: str, origin_channel: str,
                       timeout: float | None = None) -> TaskResult:
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
        files = self._with_handover_files(requester, target, goal, context, list(files or []))
        chain = (list(parent.chain) if parent else []) + [requester]
        task = Task(goal=goal, assignee=target, requester=requester,
                    session_id=session_id, root_id=root_id,
                    origin_channel=origin_channel, context=context, files=files,
                    chain=chain, parent_id=parent.id if parent else None)

        denied = self._check_limits(requester, target, goal, parent, root_id, chain)
        sources: dict[str, Path] = {}
        if denied is None:
            for name in files:
                src = self.locate_file(name, requester, root_id, session_id)
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
                self._hand_over(self.sandboxes[target], src, Path(name).name)
                self._handed.setdefault(task.id, {})[name] = (src, _digest(src))
        except Exception as exc:                      # sandbox I/O problem, not a bug here
            result = TaskResult(task.id, False, "", error=f"cannot hand over files: {exc}",
                                failure_mode=FailureMode.TOOL_ERROR)
            self.state.finish(result)
            return result

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[TaskResult] = loop.create_future()
        limit = timeout if timeout is not None else self.settings.subtask_timeout_s
        budget = _DispatchBudget(loop.time() + limit, loop.create_future())
        self._task_waiters[task.id] = fut
        self._task_budgets[task.id] = budget
        try:
            await self.bus.publish(Message(
                MsgType.TASK_ASSIGN, sender=requester, channel=task.channel,
                content=f"@{target} {goal}", payload={"task": task.to_dict()},
                receiver=target, mentions=[target]))
            while not fut.done():
                now = budget.waiting_since if budget.waiting_since is not None else loop.time()
                remaining = budget.deadline - now
                if remaining <= 0:
                    result = TaskResult(
                        task.id, False, "", error=f"no result within {limit:g}s",
                        failure_mode=FailureMode.TIMEOUT)
                    self.state.finish(result)
                    return result
                if budget.changed.done():
                    budget.changed = loop.create_future()
                # State transitions wake this wait even when a whole human pause
                # fits inside the original timeout window. Resuming keeps the
                # remaining execution budget instead of granting a fresh timeout.
                await asyncio.wait({fut, budget.changed},
                                   timeout=None if budget.waiting_since is not None else remaining,
                                   return_when=asyncio.FIRST_COMPLETED)
            return fut.result()
        finally:
            self._task_waiters.pop(task.id, None)
            self._task_budgets.pop(task.id, None)
            if not budget.changed.done():
                budget.changed.cancel()

    def _remaining_execution(self, task_id: str) -> float | None:
        """Remaining live dispatch budget, excluding time spent waiting for a human.

        Workers use this alongside their local limit so queueing time cannot
        grant a fresh timeout. Direct tasks have no dispatch budget (None).
        """
        budget = self._task_budgets.get(task_id)
        if budget is None:
            return None
        now = budget.waiting_since if budget.waiting_since is not None else asyncio.get_running_loop().time()
        return max(0.0, budget.deadline - now)

    def _with_handover_files(self, requester: str, target: str, goal: str, context: str,
                             files: list[str]) -> list[str]:
        """`files` plus what the requester evidently meant to hand over but did not list.

        A teammate sees only what is listed: a file the goal talks about but `files` leaves out does not exist
        for it, and a copy it got earlier is the OLD version once the requester has changed the file. So also
        hand over (1) every file named in the goal or context that is in the requester's workspace, and (2) the
        requester's current version of every file already in the teammate's inbox. Only the requester's own
        workspace is looked at; nothing is guessed from anywhere else."""
        mine, theirs = self.sandboxes.get(requester), self.sandboxes.get(target)
        if mine is None or theirs is None:
            return files
        out, have = list(files), {Path(f).name for f in files}

        def add(name: str) -> None:
            if name not in have:
                out.append(name)
                have.add(name)

        for name in dict.fromkeys(_FILE_NAME.findall(f"{goal}\n{context}")):
            try:
                if mine.exists(name) and mine.resolve(name).is_file():
                    add(name)
            except (OSError, ValueError, PermissionError):
                continue
        try:
            inbox = theirs.list_dir(INBOX) if theirs.exists(INBOX) else []
        except OSError:
            inbox = []
        for name in inbox:
            try:
                new, old = mine.resolve(name), theirs.resolve(f"{INBOX}/{name}")
                if new.is_file() and old.is_file() and new.read_bytes() != old.read_bytes():
                    add(name)
            except (OSError, ValueError, PermissionError):
                continue
        return out

    def stale_work(self, root_id: str) -> list[str]:
        """Work done on a version of a file that has changed since, one line per task.

        Every hand-over records a fingerprint of the file as it was handed over. A teammate's finished task whose
        file has been changed afterwards (and was not handed over again to the same teammate, who then worked on
        the new version) is out of date: whatever it wrote or approved is about the old text. This is how a
        a summary written from version 1 of a document is found after the document became version 2."""
        latest: dict[tuple[str, str], str] = {}
        for task in self.state.by_root(root_id):                       # in the order they were registered
            result = self.state.result(task.id)
            if task.id in self._handed and result is not None and result.success and not result.declined:
                for name in self._handed[task.id]:
                    latest[(task.assignee, name)] = task.id
        changed: dict[str, list[str]] = {}
        for (_, name), task_id in latest.items():
            source, was = self._handed[task_id][name]
            now = _digest(source)
            if was is not None and now is not None and now != was:
                changed.setdefault(task_id, []).append(name)
        lines = []
        for task_id, names in changed.items():
            result = self.state.result(task_id)
            made = ", ".join(result.artifacts) if result and result.artifacts else "its reply"
            lines.append(f"{self.state.get(task_id).assignee}'s work ({made}) was done on an earlier version of "
                         f"{', '.join(names)}, which has changed since")
        return lines

    def copy_back(self, requester: str, result: TaskResult, limit: int = 6, max_bytes: int = 300_000) -> list[str]:
        """Put the files a teammate reported into the inbox of whoever asked for the work, so that it can read them.

        Workspaces are private and a reply is cut after `result_summary_max_chars`: without this the requester sees
        only the first lines of a long file and, to get more, has to ask the teammate to paste it. Code is copied like
        any other file: where the team builds software the script is the result, and a lead that never receives it
        can only report that nothing was built. Files that are too large are left out, and so are compiled files; at
        most `limit` files. When more were reported, the scripts the task neither named nor handed over (the checks
        and helpers a teammate writes for itself) stay behind first, then the earliest reported. A copy of the same
        name already in the inbox is replaced. Best effort: it never fails the call. Returns the names now in the
        inbox."""
        try:
            task = self.state.get(result.task_id)
        except KeyError:
            return []
        mine, theirs = self.sandboxes.get(requester), self.sandboxes.get(task.assignee)
        if mine is None or theirs is None or mine is theirs or result.declined:
            return []
        names = [n for n in dict.fromkeys(result.artifacts)
                 if not n.lower().endswith(".pyc") and not n.startswith(f"{INBOX}/")]
        if len(names) > limit:
            asked, given = f"{task.goal}\n{task.context}", {Path(f).name for f in task.files}

            def helper(name: str) -> bool:
                base = Path(name).name
                return name.lower().endswith(_SCRIPT_SUFFIXES) and base not in given and base not in asked

            keep = [n for n in names if not helper(n)][-limit:]
            if len(keep) < limit:
                keep += [n for n in names if helper(n)][len(keep) - limit:]
            names = [n for n in names if n in keep]
        copied: list[str] = []
        for name in names:
            try:
                src = theirs.resolve(name)
                if not src.is_file() or src.stat().st_size > max_bytes:
                    continue
                self._hand_over(mine, src, Path(name).name)
                copied.append(Path(name).name)
            except Exception:
                log.warning("could not copy %s from %s to %s", name, task.assignee, requester, exc_info=True)
        return copied

    @staticmethod
    def _hand_over(target: Sandbox, src: Path, name: str) -> None:
        """Put `src` in the teammate's inbox. A copy of the same name that is already there is replaced (it is an
        older version of the file, or the same one), because import_file itself never overwrites."""
        old = f"{INBOX}/{name}"
        if target.exists(old):
            if target.resolve(old).is_file() and target.resolve(old).read_bytes() == Path(src).read_bytes():
                return
            target.delete(old)
        target.import_file(src, name)

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
        if parent:
            # A request's lead coordinates the whole team (assign, review, fix, release...), so it
            # may delegate more often than a worker that only asks a teammate for help now and then.
            allowed = s.max_lead_delegations if parent.parent_id is None else s.max_delegations_per_task
            if self._delegations.get(parent.id, 0) >= allowed:
                return f"task {parent.id} already delegated {allowed} times"
        tries = self._attempts.get((root_id, target, _norm(goal)), [])
        attempts = sum(1 for tid in tries if self.state.get(tid).status != TaskStatus.DECLINED)
        if attempts > s.max_retries_same_goal:       # first try + max_retries retries
            return f"same goal already tried {attempts} times on {target}"
        return None

    def locate_file(self, name: str, requester: str, root_id: str,
                    session_id: str | None = None) -> Path | None:
        """Where `name` lives: the requester's own sandbox, else the workspace of the
        agent whose result listed it as an artifact, newest first: this root's results
        first, then those of the roots that came before it in the same session (a
        follow-up request such as "extend the system we just built" must find the files of
        the first one; a later root never leaks backwards). The request layer uses it to
        collect the deliverables."""
        owners = [requester] + [t.assignee for t in self._tasks_newest_first(root_id, session_id)
                                if (r := self.state.result(t.id)) and name in r.artifacts]
        for owner in owners:
            sb = self.sandboxes.get(owner)
            try:
                if sb and sb.exists(name):
                    return sb.resolve(name)
            except PermissionError:
                return None
        return None

    def _tasks_newest_first(self, root_id: str, session_id: str | None = None) -> list[Task]:
        """Tasks of `root_id` (newest first), then those of the earlier roots of its session."""
        mine = self.state.by_root(root_id)
        session = mine[0].session_id if mine else session_id
        earlier: list[Task] = []
        if session:
            for t in self.state.in_session(session):          # registration order
                if t.root_id == root_id:
                    break
                earlier.append(t)
        return list(reversed(mine)) + list(reversed(earlier))

    def root_artifacts(self, root_id: str) -> list[tuple[str, str]]:
        """(agent, file) for every file the successful tasks of this root wrote, oldest first,
        without repeats. What a lead-run request delivers."""
        seen: dict[tuple[str, str], None] = {}
        for t in self.state.by_root(root_id):
            r = self.state.result(t.id)
            if r and r.success and not r.declined:
                for name in r.artifacts:
                    seen.setdefault((t.assignee, name), None)
        return list(seen)

    def delivery_owner(self, root_id: str, lead: str, name: str) -> str:
        """Whose copy of a file the lead listed is handed to the human: the lead's own or a teammate's.

        A file no teammate reported in this request is the lead's. One a teammate wrote that the lead does not have, or
        has unchanged, is the teammate's (the newest task that reported it). When both have it and the two differ, the
        latest revision is taken: the lead's if it was written after the teammate's, unless it is byte for byte what
        that teammate was handed to work on (then the teammate's file is the revision and the lead's copy the text it
        started from). The teammate's copy used to win always, so a lead that revised a teammate's draft through two
        review rounds handed in the first draft."""
        writer = None
        for task in self.state.by_root(root_id):
            result = self.state.result(task.id)
            if task.assignee != lead and result and result.success and not result.declined and name in result.artifacts:
                writer = task
        if writer is None:
            return lead
        mine, theirs = self.sandboxes.get(lead), self.sandboxes.get(writer.assignee)
        if mine is None or theirs is None:
            return writer.assignee
        try:
            own, other = mine.resolve(name), theirs.resolve(name)
            if not own.is_file():
                return writer.assignee
            if not other.is_file():
                return lead
            text = _digest(own)
            if text is None or text == _digest(other):
                return writer.assignee
            started_from = {digest for handed, (_, digest) in self._handed.get(writer.id, {}).items()
                            if Path(handed).name == Path(name).name}
            if text in started_from:
                return writer.assignee
            return lead if own.stat().st_mtime_ns > other.stat().st_mtime_ns else writer.assignee
        except (OSError, ValueError):
            return writer.assignee

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
        self.start_clock(task.root_id)
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

    # ---- time budget of a request -------------------------------------------

    def start_clock(self, root_id: str) -> None:
        """The request's time budget starts now (only the first call counts)."""
        self._root_started.setdefault(root_id, self.clock())

    def time_left(self, root_id: str) -> float | None:
        """Seconds left of the request's time budget (negative when it is over), or None without a budget.
        Time spent waiting for the human is not counted."""
        budget = self.settings.request_budget_s
        if budget <= 0:
            return None
        started = self._root_started.setdefault(root_id, self.clock())
        return (started + budget + self._root_human_wait.get(root_id, 0.0) + self._root_extra.get(root_id, 0.0)
                - self.clock())

    def grant_review_reserve(self, root_id: str) -> float:
        """A review did not pass: top the time left up to `review_reserve_s`, so that there is time to fix what it
        found and to have the reviewer check the fix. Only the missing part is added, and only
        `max_review_extensions` times per request. Returns the seconds added (0: no budget, enough time, or used up)."""
        s = self.settings
        left = self.time_left(root_id)
        if (left is None or s.review_reserve_s <= 0 or left >= s.review_reserve_s
                or self._root_grants.get(root_id, 0) >= s.max_review_extensions):
            return 0.0
        added = s.review_reserve_s - left
        self._root_extra[root_id] = self._root_extra.get(root_id, 0.0) + added
        self._root_grants[root_id] = self._root_grants.get(root_id, 0) + 1
        return added

    @staticmethod
    def review_verdict(goal: str, result: TaskResult) -> str | None:
        """'fail' or 'pass' when `result` answers a request to review or check something, else None. Judged by the
        words of the answer: an upper-case FAIL (or APPROVE WITH CHANGES) or "approve with conditions" fails it even when
        some points passed; PASS or APPROVE passes it; without either, wording such as "must fix" fails it."""
        if result.declined or not result.success or not _REVIEW_GOAL.search((goal or "")[:120]):   # a review says so first
            return None
        text = " ".join(filter(None, [result.summary, *result.open_issues]))
        if _FAIL_UPPER.search(text) or _FAIL_PHRASE.search(text):
            return "fail"
        if _PASS.search(text):
            return "pass"
        return "fail" if _FAIL_WEAK.search(text) else None

    def set_requirements(self, root_id: str, items: list[str]) -> None:
        """What the request explicitly requires (quantities, sizes, formats, coverage), as the lead listed them."""
        self._requirements[root_id] = list(items)

    def requirements(self, root_id: str) -> list[str]:
        return list(self._requirements.get(root_id, []))

    def review_rounds(self, root_id: str, assignee: str, files: list[str]) -> int:
        """How often `assignee` has already been asked, in this request, to review the same file: the most for any one
        of `files`. A review that was refused does not count. Zero when no file is named."""
        names = {Path(f).name for f in files}
        counts: dict[str, int] = {}
        for task in self.state.by_root(root_id):
            result = self.state.result(task.id)
            if (task.assignee != assignee or not _REVIEW_VERB.search(task.goal[:80])
                    or (result is not None and (result.error or "").startswith("refused:"))):
                continue
            for name in names & {Path(n).name for n in self._handed.get(task.id, {})}:
                counts[name] = counts.get(name, 0) + 1
        return max(counts.values(), default=0)

    @staticmethod
    def is_review_request(goal: str) -> bool:
        return bool(_REVIEW_VERB.search((goal or "")[:80]))

    def reviewed_files(self, root_id: str) -> set[str]:
        """Base names of the files a reviewer has been given in this request (a successful task whose goal asks
        for a review or check), and of the files such reviewers wrote themselves (their reports are not deliverables
        that need a review)."""
        seen: set[str] = set()
        for task in self.state.by_root(root_id):
            result = self.state.result(task.id)
            if result is None or not result.success or result.declined or not _REVIEW_GOAL.search(task.goal[:120]):
                continue
            seen.update(Path(name).name for name in self._handed.get(task.id, {}))
            seen.update(Path(name).name for name in result.artifacts)
        return seen

    def unreviewed(self, root_id: str, deliverables: list[str]) -> list[str]:
        """The deliverables (scripts left out) that no reviewer was ever given."""
        reviewed = self.reviewed_files(root_id)
        return [n for n in dict.fromkeys(deliverables)
                if not n.lower().endswith(_SCRIPT_SUFFIXES) and Path(n).name not in reviewed]

    def open_reviews(self, root_id: str) -> list[str]:
        """The reviewers whose latest verdict in this request is a fail: nobody has confirmed the fix since."""
        latest: dict[str, tuple[str, str]] = {}
        for task in self.state.by_root(root_id):
            result = self.state.result(task.id)
            verdict = self.review_verdict(task.goal, result) if result is not None else None
            if verdict:
                summary = " ".join(result.summary.split())
                latest[task.assignee] = (verdict, summary[:220] + ("…" if len(summary) > 220 else ""))
        return [f"{who}'s latest verdict is not a pass: {text}" for who, (verdict, text) in latest.items()
                if verdict == "fail"]

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
        The request layer has no Task when it asks for clarification, so it passes
        task_id=None. With a task_id the task is WAITING_HUMAN meanwhile.
        Returns CANCELLED_ANSWER if the root is cancelled or the task has already
        ended. Callers use the task's stored result to distinguish timeout from
        user cancellation."""
        if root_id in self._cancelled_roots:
            return CANCELLED_ANSWER
        if task_id:
            try:
                if self.state.get(task_id).status.finished:
                    return CANCELLED_ANSWER
            except KeyError:
                return CANCELLED_ANSWER
            remaining = self._remaining_execution(task_id)
            if remaining is not None and remaining <= 0:
                # The clock may have expired before dispatch's waiter resumes.
                # Finish it now rather than creating an approval nobody can cancel.
                self._on_result(TaskResult(
                    task_id, False, "", error=f"no result within {self.settings.subtask_timeout_s}s",
                    failure_mode=FailureMode.TIMEOUT))
                return CANCELLED_ANSWER
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
        asked_at = self.clock()
        try:
            await self.bus.publish(Message(
                MsgType.HITL_REQUEST, sender=requester, channel=origin_channel,
                content=text, receiver=HUMAN, mentions=[HUMAN],
                payload={"request_id": request_id, "task_id": task_id, "root_id": root_id,
                         "kind": kind.value, "question": question, "options": options}))
            answer = await fut
        finally:
            self._root_human_wait[root_id] = self._root_human_wait.get(root_id, 0.0) + self.clock() - asked_at
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

    def root_cancelled(self, root_id: str) -> bool:
        return root_id in self._cancelled_roots

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
        for key, root in list(self._hitl_root.items()):      # also the request layer's questions
            waiter = self._hitl_waiters.get(key)
            if root == root_id and waiter and not waiter.done():
                waiter.set_result(CANCELLED_ANSWER)

    def cancel_session(self, session_id: str) -> list[str]:
        """Cancel every root that still has unfinished tasks in the session (for /cancel in
        a DM, where the request layer is not involved). Returns the roots it cancelled."""
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
                budget = self._task_budgets.get(task_id)
                if budget is not None:
                    budget.set_waiting(status == TaskStatus.WAITING_HUMAN,
                                       asyncio.get_running_loop().time())
        except KeyError:
            pass
