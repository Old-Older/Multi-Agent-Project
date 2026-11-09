"""Shared session board (design §3.1, D17).

Owner: JIAN Yimin.

Maintained by code from structured messages, never summarized by an LLM, so
IDs, file names and open items are never lost. One board per session
(the group chat, or one DM conversation).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mas.core.message import HUMAN, Message, MsgType
from mas.core.task import TaskResult


@dataclass
class RootRecord:
    root_id: str
    human_messages: list[str] = field(default_factory=list)   # verbatim, request + interjections
    plan: str = ""                    # latest "remaining steps" line from the Orchestrator
    finish_summary: str = ""          # from finish(summary, ...)
    deliverables: list[str] = field(default_factory=list)
    finished: bool = False


@dataclass
class TaskEntry:
    """One sub-task as the board sees it, built from TASK_ASSIGN / TASK_RESULT."""
    id: str
    root_id: str
    assignee: str
    goal: str
    state: str = "running"            # running | done | failed | declined
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)
    refs: dict[str, str] = field(default_factory=dict)
    open_issues: list[str] = field(default_factory=list)
    error: str = ""
    suggest: str = ""


@dataclass
class HitlEntry:
    request_id: str
    root_id: str
    question: str
    answer: str | None = None         # None = still waiting for the human


_SENTENCE_END = re.compile(r"[。！？!?\n]|\.(?:\s|$)")


def _first_sentence(text: str) -> str:
    text = text.strip()
    m = _SENTENCE_END.search(text)
    return text[:m.start()].strip() if m else text


def _cap(text: str, n: int | None) -> str:
    text = " ".join(text.split())
    return text if n is None or len(text) <= n else text[:n] + "…"


class SessionBoard:
    def __init__(self, session_id: str, max_chars: int = 2000) -> None:
        self.session_id = session_id
        self.max_chars = max_chars
        self.roots: dict[str, RootRecord] = {}
        self.tasks: dict[str, TaskEntry] = {}
        self.hitl: dict[str, HitlEntry] = {}
        # Human messages seen before the Orchestrator opened a root for them.
        self._pending_human: list[str] = []

    # ---- updates ---------------------------------------------------------

    def on_message(self, msg: Message) -> None:
        """Update the board from any message of this session.

        CHAT from HUMAN -> human_messages (slash commands are skipped);
        TASK_ASSIGN -> a running task; TASK_RESULT -> done / failed / declined
        with artifacts, refs and open_issues; HITL_* -> pending and answered
        requests. STATUS and agent chatter are ignored.
        """
        if msg.type == MsgType.CHAT and msg.sender == HUMAN:
            self._on_human(msg.content)
        elif msg.type == MsgType.TASK_ASSIGN:
            t = msg.payload["task"]
            self._ensure_root(t["root_id"])
            self.tasks[t["id"]] = TaskEntry(
                id=t["id"], root_id=t["root_id"], assignee=t["assignee"], goal=t["goal"])
        elif msg.type == MsgType.TASK_RESULT:
            self._on_result(TaskResult.from_dict(msg.payload["result"]))
        elif msg.type == MsgType.HITL_REQUEST:
            p = msg.payload
            task = self.tasks.get(p.get("task_id", ""))
            root_id = task.root_id if task else self._current_root_id()
            self.hitl[p["request_id"]] = HitlEntry(p["request_id"], root_id, p["question"])
        elif msg.type == MsgType.HITL_RESPONSE:
            entry = self.hitl.get(msg.payload["request_id"])
            if entry:
                entry.answer = msg.payload["answer"]

    def _on_human(self, text: str) -> None:
        text = text.strip()
        if not text or text.startswith("/"):
            return
        root = self._current_root()
        if root and not root.finished:
            root.human_messages.append(text)      # interjection
        else:
            self._pending_human = (self._pending_human + [text])[-20:]

    def _on_result(self, r: TaskResult) -> None:
        entry = self.tasks.get(r.task_id)
        if entry is None:
            return
        entry.state = "declined" if r.declined else "done" if r.success else "failed"
        entry.summary = r.summary
        entry.artifacts = list(r.artifacts)
        entry.refs = dict(r.refs)
        entry.open_issues = list(r.open_issues)
        entry.error = r.error or ""
        entry.suggest = r.suggest or ""

    def start_root(self, root_id: str, human_text: str) -> None:
        """Open a root. The human's message was usually already seen by on_message;
        it is adopted from the pending buffer instead of being recorded twice."""
        if root_id in self.roots:
            return
        text = human_text.strip()
        if text in self._pending_human:
            idx = len(self._pending_human) - 1 - self._pending_human[::-1].index(text)
            del self._pending_human[idx]
        self.roots[root_id] = RootRecord(root_id, human_messages=[text])

    def _ensure_root(self, root_id: str) -> None:
        """A task may reference a root nobody called start_root for (a direct DM
        task): open it with the latest pending human message."""
        if root_id not in self.roots:
            text = self._pending_human.pop() if self._pending_human else ""
            self.roots[root_id] = RootRecord(root_id, human_messages=[text] if text else [])

    def set_plan(self, root_id: str, plan: str) -> None:
        self.roots[root_id].plan = plan.strip()

    def finish_root(self, root_id: str, summary: str, deliverables: list[str]) -> None:
        root = self.roots[root_id]
        root.finish_summary = summary.strip()
        root.deliverables = list(deliverables)
        root.finished = True

    def _current_root(self) -> RootRecord | None:
        """Latest root still running, else the latest one."""
        if not self.roots:
            return None
        unfinished = [r for r in self.roots.values() if not r.finished]
        return unfinished[-1] if unfinished else list(self.roots.values())[-1]

    def _current_root_id(self) -> str:
        root = self._current_root()
        return root.root_id if root else ""

    # ---- rendering -------------------------------------------------------

    def render(self, max_chars: int | None = None) -> str:
        """Text injected into a worker's system prompt.

        Earlier roots are always one line. When over the limit, all rule based:
        drop the oldest earlier roots (leaving a hint line), then truncate
        done-task summaries. Never drops the current human messages, IDs, file
        names or open items, so the result may exceed the limit in that case.
        """
        limit = max_chars or self.max_chars
        current = self._current_root()
        earlier = [r for r in self.roots.values() if r is not current]
        text = ""
        for dropped in range(len(earlier) + 1):
            text = self._build(current, earlier, dropped, None)
            if len(text) <= limit:
                return text
        for cap in (80, 40, 20):
            text = self._build(current, earlier, len(earlier), cap)
            if len(text) <= limit:
                return text
        return text

    def _build(self, current: RootRecord | None, earlier: list[RootRecord],
               dropped: int, summary_cap: int | None) -> str:
        if current is None:
            return f"## 会话看板（session {self.session_id}）\n（暂无内容）"
        out = [f"## 会话看板（session {self.session_id}，根任务 {current.root_id}）"]
        out.append("人类原话：")
        for i, m in enumerate(current.human_messages):
            out.append(f'  - {"（插话）" if i else ""}"{m}"')

        mine = [t for t in self.tasks.values() if t.root_id == current.root_id]
        done = [t for t in mine if t.state == "done"]
        bad = [t for t in mine if t.state in ("failed", "declined")]
        running = [t for t in mine if t.state == "running"]
        asks = [h for h in self.hitl.values() if h.root_id == current.root_id]

        if done:
            out.append("已完成：")
            for t in done:
                line = f"  - {t.id} {t.assignee}「{t.goal}」"
                if t.artifacts:
                    line += "→ " + ", ".join(t.artifacts)
                if t.refs:
                    line += "｜" + ", ".join(f"{k}={v}" for k, v in t.refs.items())
                if t.summary:
                    line += "｜要点：" + _cap(t.summary, summary_cap)
                out.append(line)
        if bad:
            out.append("失败/拒绝：")
            for t in bad:
                reason = _cap(_first_sentence(t.error or t.summary), 60)
                if t.state == "declined":
                    line = f"  - {t.id} {t.assignee} 拒绝：{reason}"
                    if t.suggest:
                        line += f"，建议 {t.suggest}"
                else:
                    line = f"  - {t.id} {t.assignee} 失败：{reason}"
                out.append(line)
        answered = [h for h in asks if h.answer is not None]
        if answered:
            out.append("人类决定：")
            out += [f"  - {h.request_id}「{h.question}」→ {h.answer}" for h in answered]

        todo = [f"  - {t.id} {t.assignee} 执行中「{t.goal}」" for t in running]
        todo += [f"  - {h.request_id} 等待人类：{h.question}" for h in asks if h.answer is None]
        for t in done:
            todo += [f"  - 遗留（{t.id}）：{issue}" for issue in t.open_issues]
        if current.plan:
            todo.append(f"  - 剩余计划：{current.plan}")
        if todo:
            out.append("未办：")
            out += todo

        if earlier:
            out.append("早先：")
            if dropped:
                out.append(f"  - 另有 {dropped} 个早先任务，可用 read_group 查看")
            for r in earlier[dropped:]:
                out.append("  - " + self._root_line(r))
        return "\n".join(out)

    @staticmethod
    def _root_line(r: RootRecord) -> str:
        gist = _first_sentence(r.finish_summary) if r.finish_summary else ""
        if not gist:
            gist = (r.human_messages[0] if r.human_messages else "")[:40]
        line = f"{r.root_id} {gist}"
        if r.deliverables:
            line += " → " + ", ".join(r.deliverables)
        return line

    # ---- persistence -----------------------------------------------------

    def save(self, path: Path) -> None:
        data = {
            "session_id": self.session_id,
            "max_chars": self.max_chars,
            "roots": [asdict(r) for r in self.roots.values()],
            "tasks": [asdict(t) for t in self.tasks.values()],
            "hitl": [asdict(h) for h in self.hitl.values()],
            "pending_human": self._pending_human,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> SessionBoard:
        data = json.loads(path.read_text(encoding="utf-8"))
        board = cls(data["session_id"], data["max_chars"])
        board.roots = {r["root_id"]: RootRecord(**r) for r in data["roots"]}
        board.tasks = {t["id"]: TaskEntry(**t) for t in data["tasks"]}
        board.hitl = {h["request_id"]: HitlEntry(**h) for h in data["hitl"]}
        board._pending_human = list(data["pending_human"])
        return board
