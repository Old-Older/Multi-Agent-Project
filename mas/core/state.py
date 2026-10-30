"""Task state table (design §2.1, §4, §5).

Owner: JIAN Yimin.

Single source of truth for every task in every session. Read by /status,
the session board and the eval harness; written only by the Router.
"""
from __future__ import annotations

from mas.core.task import Task, TaskResult, TaskStatus


class StateTable:
    def register(self, task: Task) -> None:
        raise NotImplementedError

    def update(self, task_id: str, status: TaskStatus, note: str = "") -> None:
        raise NotImplementedError

    def finish(self, result: TaskResult) -> None:
        """Store the result and set the final status (DONE / FAILED / DECLINED)."""
        raise NotImplementedError

    def get(self, task_id: str) -> Task:
        raise NotImplementedError

    def result(self, task_id: str) -> TaskResult | None:
        raise NotImplementedError

    def by_root(self, root_id: str) -> list[Task]:
        raise NotImplementedError

    def active(self, session_id: str) -> list[Task]:
        """Tasks of the session that are not finished yet."""
        raise NotImplementedError

    def status_text(self, session_id: str) -> str:
        """Plain-text answer for the /status command (no LLM)."""
        raise NotImplementedError
