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
        """Plain-text answer for the /status command (no LLM)."""
        tasks = [t for t in self._tasks.values() if t.session_id == session_id]
        if not tasks:
            return "当前会话还没有任务。"
        lines = []
        for t in tasks:
            line = f"{t.id} {t.assignee} [{t.status.value}]「{_clip(t.goal)}」"
            if t.id in self._notes:
                line += f"：{_clip(self._notes[t.id])}"
            lines.append(line)
        running = sum(1 for t in tasks if not t.status.finished)
        return f"任务 {len(tasks)} 个，进行中 {running} 个：\n" + "\n".join(lines)


def _clip(text: str, n: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n] + "…"
