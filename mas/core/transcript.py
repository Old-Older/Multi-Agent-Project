"""Transcript: the whole conversation of a run as one readable Markdown file.

Owner: JIAN Yimin.

Grading reads the complete dialogue and the outputs (a model judges them), so the dialogue has to
be exportable as it happened: what the human said, who led, who delegated what to whom, what the
agents asked the human and what the human answered, every result, and how each request ended.
A bus observer collects it, so nothing in the agents has to cooperate and nothing costs an LLM
call. Internal progress lines (STATUS) are left out; they say nothing the results do not.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from mas.core.bus import MessageBus
from mas.core.message import HUMAN, ORCHESTRATOR, Message, MsgType, is_group

log = logging.getLogger(__name__)


def _clock(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def _elapsed(seconds: float) -> str:
    m, s = divmod(int(max(seconds, 0)), 60)
    return f"+{m:02d}:{s:02d}"


class Transcript:
    """Collects every message of the run (groups and private chats).

    `outcomes` (optional) is read when the file is rendered, to end it with one line per request.
    With `path` set the file is rewritten whenever a request ends (the last reply of a request is
    the one carrying `final` in its payload), so a crash never loses what was already said."""

    def __init__(self, bus: MessageBus, *, title: str = "Transcript", path: Path | None = None,
                 team: Mapping[str, str] | None = None,
                 outcomes: Callable[[], Mapping[str, object]] | None = None) -> None:
        self.title = title
        self.path = path
        self.team = dict(team or {})                       # agent id -> role name
        self.outcomes = outcomes
        self.started = time.time()
        self.messages: list[Message] = []
        bus.add_observer(self._on_message)

    # ---- collecting ----------------------------------------------------------------

    def _on_message(self, msg: Message) -> None:
        if msg.type == MsgType.STATUS:
            return
        self.messages.append(msg)
        if msg.payload.get("final") and self.path is not None:
            self.save()

    # ---- rendering -----------------------------------------------------------------

    def render(self) -> str:
        out = [f"# {self.title}", "",
               f"Started {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.started))}."]
        if self.team:
            out += ["", "## Team", ""] + [f"- `{a}`: {role}" for a, role in self.team.items()]
        out += ["", "## Conversation", ""]
        if not self.messages:
            out.append("(nothing was said)")
        for msg in self.messages:
            out += self._entry(msg)
        summary = self._summary()
        if summary:
            out += ["", "## How the requests ended", ""] + summary
        return "\n".join(out).rstrip() + "\n"

    def dialogue(self, since: float = 0.0, until: float | None = None) -> str:
        """Just the conversation (no header, team or summary) between two timestamps.
        Evaluation uses it to show a grader what happened during one task."""
        lines: list[str] = []
        for msg in self.messages:
            if msg.ts >= since and (until is None or msg.ts < until):
                lines += self._entry(msg)
        return "\n".join(lines).strip()

    def save(self, path: Path | None = None) -> Path | None:
        """Write the file (to `path`, else to the path given at construction). Never raises:
        a transcript that cannot be written must not stop a run."""
        target = path or self.path
        if target is None:
            return None
        try:
            target = Path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.render(), encoding="utf-8")
        except OSError:
            log.warning("Could not write the transcript to %s", target, exc_info=True)
            return None
        return target

    def _entry(self, msg: Message) -> list[str]:
        when = f"{_clock(msg.ts)} ({_elapsed(msg.ts - self.started)})"
        where = "" if is_group(msg.channel) else f" in the private chat {msg.channel.split(':', 1)[1]}"
        p = msg.payload
        if msg.type == MsgType.CHAT:
            if msg.sender == HUMAN:
                head = f"{HUMAN} → {msg.receiver or 'the team'}{where}"
            elif p.get("final"):
                status = "done" if p.get("success") else f"failed ({p.get('failure_mode') or 'unknown'})"
                head = f"{msg.sender} → {HUMAN} · FINAL REPLY to {p.get('root_id')} · {status}"
            else:
                head = f"{self._name(msg.sender)} → {msg.receiver or 'everyone'}{where}"
            return self._block(when, head, msg.content)
        if msg.type == MsgType.TASK_ASSIGN:
            task = p.get("task", {})
            if msg.sender == ORCHESTRATOR:
                head = f"request {task.get('root_id', '')} handed to its lead {msg.receiver} (task `{task.get('id', '')}`)"
                return self._block(when, head, "")
            head = f"{msg.sender} delegates to {msg.receiver} · task `{task.get('id', '')}`{where}"
            body = task.get("goal") or msg.content
            if task.get("files"):
                body += f"\n\nFiles handed over: {', '.join(task['files'])}"
            return self._block(when, head, body)
        if msg.type == MsgType.TASK_RESULT:
            result = p.get("result", {})
            if msg.receiver == ORCHESTRATOR:
                return []                                      # said again by the final reply
            how = "declined" if result.get("declined") else "done" if result.get("success") else "FAILED"
            head = f"{msg.sender} reports to {msg.receiver} · task `{result.get('task_id', '')}` · {how}{where}"
            body = msg.content
            if result.get("artifacts"):
                body += f"\n\nFiles: {', '.join(result['artifacts'])}"
            return self._block(when, head, body)
        if msg.type == MsgType.HITL_REQUEST:
            options = f"\n\nOptions: {' / '.join(p['options'])}" if p.get("options") else ""
            head = f"{msg.sender} asks the human · {p.get('request_id')} ({p.get('kind')}){where}"
            return self._block(when, head, f"{p.get('question', msg.content)}{options}")
        if msg.type == MsgType.HITL_RESPONSE:
            return self._block(when, f"human answers · {p.get('request_id')}{where}", str(p.get("answer", "")))
        return []

    @staticmethod
    def _name(agent_id: str) -> str:
        return "system" if agent_id == ORCHESTRATOR else agent_id

    @staticmethod
    def _block(when: str, head: str, body: str) -> list[str]:
        lines = [f"### {when} · {head}"]
        if body.strip():
            lines += ["", *(f"> {line}" if line.strip() else ">" for line in body.strip().splitlines())]
        return lines + [""]

    def _summary(self) -> list[str]:
        outcomes = dict(self.outcomes()) if self.outcomes else {}
        if not outcomes:
            return []
        rows = ["| request | lead | result | failure | seconds | deliverables |", "|---|---|---|---|---|---|"]
        for root, o in outcomes.items():
            failure = getattr(o, "failure_mode", None)
            rows.append(f"| {root} | {getattr(o, 'lead', '') or '-'} | {'done' if o.success else 'failed'} | "
                        f"{getattr(failure, 'value', failure) or '-'} | {o.duration:.1f} | "
                        f"{', '.join(o.deliverables) or '-'} |")
        return rows
