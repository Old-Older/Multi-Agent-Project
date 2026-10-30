"""Shared session board (design §3.1, D17).

Owner: JIAN Yimin.

Maintained by code from structured messages, never summarized by an LLM, so
IDs, file names and open items are never lost. One board per session
(the group chat, or one DM conversation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mas.core.message import Message


@dataclass
class RootRecord:
    root_id: str
    human_messages: list[str] = field(default_factory=list)   # verbatim, request + interjections
    plan: str = ""                    # latest "remaining steps" line from the Orchestrator
    finish_summary: str = ""          # from finish(summary, ...)
    deliverables: list[str] = field(default_factory=list)
    finished: bool = False


class SessionBoard:
    def __init__(self, session_id: str, max_chars: int = 2000) -> None:
        self.session_id = session_id
        self.max_chars = max_chars

    def on_message(self, msg: Message) -> None:
        """Update the board from any message of this session.

        CHAT from HUMAN -> human_messages; TASK_RESULT -> done / failed / declined
        lists with artifacts, refs and open_issues; HITL_* -> pending and answered
        requests.
        """
        raise NotImplementedError

    def start_root(self, root_id: str, human_text: str) -> None:
        raise NotImplementedError

    def set_plan(self, root_id: str, plan: str) -> None:
        raise NotImplementedError

    def finish_root(self, root_id: str, summary: str, deliverables: list[str]) -> None:
        raise NotImplementedError

    def render(self, max_chars: int | None = None) -> str:
        """Text injected into a worker's system prompt.

        Compression order when too long (all rule based): finished roots -> one
        line from the first sentence of finish_summary; then drop oldest roots;
        then truncate done-task summaries. Never drops current human messages,
        IDs, file names or open items.
        """
        raise NotImplementedError

    def save(self, path: Path) -> None:
        raise NotImplementedError

    @classmethod
    def load(cls, path: Path) -> SessionBoard:
        raise NotImplementedError
