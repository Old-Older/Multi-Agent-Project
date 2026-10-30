"""Per-agent memory (design §8, D13, D5).

Owner: JIAN Yimin.

Two uses of the same records:
  recall()  -> past lessons injected into the worker prompt ("how to do it")
  profile() -> capability profile shown to the Orchestrator ("who should do it")
Neither calls an LLM. The only LLM call is the async failure reflection that
produces Experience.lesson, done by the worker after it has returned.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Experience:
    task_id: str
    task_goal: str
    tags: list[str]                   # task type, derived from tools used, e.g. ["code", "git"]
    success: bool
    summary: str
    lesson: str = ""                  # empty on success; one sentence on failure
    ts: float = field(default_factory=time.time)


class Memory(ABC):
    @abstractmethod
    def add(self, exp: Experience) -> None: ...

    @abstractmethod
    def recall(self, query: str, k: int = 3) -> list[Experience]:
        """Most relevant past experiences for query (keyword overlap)."""

    @abstractmethod
    def profile(self, max_chars: int = 300) -> str:
        """Success counts per tag plus recent failure lessons, e.g.
        '近期表现：code 8/10 成功，git 3/3 成功。已知短板：……'"""


class JsonlMemory(Memory):
    """One JSONL file per agent: <memory_dir>/<agent_id>.jsonl."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def add(self, exp: Experience) -> None:
        raise NotImplementedError

    def recall(self, query: str, k: int = 3) -> list[Experience]:
        raise NotImplementedError

    def profile(self, max_chars: int = 300) -> str:
        raise NotImplementedError
