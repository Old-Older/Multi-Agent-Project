"""Task state table (design §2.1, §4, §5).

Owner: JIAN Yimin.

Single source of truth for every task in every session. Read by /status,
the session board and the eval harness; written only by the Router.
"""
from __future__ import annotations

from mas.core.task import Task, TaskResult, TaskStatus


class StateTable:
    """In-memory table. register() keeps the Task object itself, so the status
    shown here is always the one on the Task."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._results: dict[str, TaskResult] = {}
        self._notes: dict[str, str] = {}

    def register(self, task: Task) -> None:
        if task.id in self._tasks:
            raise ValueError(f"task {task.id} already registered")
        self._tasks[task.id] = task

    def update(self, task_id: str, status: TaskStatus, note: str = "") -> None:
        task = self.get(task_id)
        task.status = status
        if note:
            self._notes[task_id] = note

    def finish(self, result: TaskResult) -> None:
        """Store the result and set the final status (DONE / FAILED / DECLINED).
        A task already CANCELLED keeps that status; its late result is still stored."""
        task = self.get(result.task_id)
        self._results[result.task_id] = result
        if task.status == TaskStatus.CANCELLED:
            return
        if result.declined:
            task.status = TaskStatus.DECLINED
        elif result.success:
            task.status = TaskStatus.DONE
        else:
            task.status = TaskStatus.FAILED
        if result.error:
            self._notes[task.id] = result.error

    def get(self, task_id: str) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError:
            raise KeyError(f"unknown task {task_id}") from None

    def result(self, task_id: str) -> TaskResult | None:
        return self._results.get(task_id)

    def by_root(self, root_id: str) -> list[Task]:
        return [t for t in self._tasks.values() if t.root_id == root_id]

    def active(self, session_id: str) -> list[Task]:
        """Tasks of the session that are not finished yet."""
        return [t for t in self._tasks.values()
                if t.session_id == session_id and not t.status.finished]

    def status_text(self, session_id: str) -> str:
        """Plain-text answer for the /status command (no LLM).

        The current root (the latest one that still has unfinished tasks, else the latest
        one) lists its tasks one by one. Every earlier root is a single line, so the answer
        does not grow with the length of the chat."""
        tasks = [t for t in self._tasks.values() if t.session_id == session_id]
        if not tasks:
            return "No tasks in this session yet."
        roots: dict[str, list[Task]] = {}
        for t in tasks:
            roots.setdefault(t.root_id, []).append(t)
        ids = list(roots)
        current = next((r for r in reversed(ids) if any(not t.status.finished for t in roots[r])), ids[-1])
        mine = roots[current]
        running = sum(1 for t in mine if not t.status.finished)
        lines = [f"{current}: {_n(len(mine), 'task')}, {running} in progress:"]
        for t in mine:
            line = f"  {t.id} {t.assignee} [{t.status.value}] \"{_clip(t.goal)}\""
            if t.id in self._notes:
                line += f": {_clip(self._notes[t.id])}"
            lines.append(line)
        earlier = [r for r in ids if r != current]
        if earlier:
            lines.append("Earlier requests:")
            lines += [f"  {r}: {_n(len(roots[r]), 'task')}, {self._counts(roots[r])}" for r in earlier]
        return "\n".join(lines)

    @staticmethod
    def _counts(tasks: list[Task]) -> str:
        """'all done', or e.g. 'done 3, failed 1' for a root that did not go entirely well."""
        if all(t.status == TaskStatus.DONE for t in tasks):
            return "all done"
        names = {TaskStatus.DONE: "done", TaskStatus.FAILED: "failed", TaskStatus.DECLINED: "declined",
                 TaskStatus.CANCELLED: "cancelled"}
        parts = [f"{label} {n}" for status, label in names.items()
                 if (n := sum(1 for t in tasks if t.status == status))]
        unfinished = sum(1 for t in tasks if not t.status.finished)
        if unfinished:
            parts.append(f"unfinished {unfinished}")
        return ", ".join(parts)


def _n(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _clip(text: str, n: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + "…"
