"""Evaluation harness (design §10, D16).

Owner: LI Heyang.

Each case runs in a fresh session with AutoResponder; only agent memory
carries over between cases.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from mas.config import Settings
from mas.core.task import FailureMode

# checker(output_dir) -> True if the deliverables are correct
Checker = Callable[[Path], bool]


@dataclass
class EvalCase:
    id: str
    prompt: str
    category: str                     # code | doc | search | file | git
    checker: Checker | None = None    # None = success means "finished without failure"


@dataclass
class EvalRecord:
    case_id: str
    category: str
    success: bool
    subtask_total: int
    subtask_done: int
    duration: float                   # seconds, from submit to final reply
    orchestrator_rounds: int
    hitl_count: int
    failure_mode: FailureMode | None = None
    output_dir: str = ""
    notes: list[str] = field(default_factory=list)


async def run_case(case: EvalCase, settings: Settings) -> EvalRecord:
    """Build a fresh system (new session, shared memory dir), submit the prompt
    through AutoResponder, wait for the final reply, run the checker."""
    raise NotImplementedError


async def run_suite(cases: list[EvalCase], settings: Settings) -> list[EvalRecord]:
    raise NotImplementedError


def summarize(records: list[EvalRecord]) -> dict[str, object]:
    """Completion rate (overall and per category), subtask completion rate,
    mean / p50 / max duration, failure-mode counts."""
    raise NotImplementedError
