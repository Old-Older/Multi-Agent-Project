"""Task and result model (design §4, §5, §3.1).

Owner: JIAN Yimin. Changes need agreement from both members.

One Task is created for every call_<agent> tool call, whether it comes from
the Orchestrator or from a Worker re-delegating.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    DONE = "done"
    FAILED = "failed"
    DECLINED = "declined"
    CANCELLED = "cancelled"

    @property
    def finished(self) -> bool:
        return self in (TaskStatus.DONE, TaskStatus.FAILED,
                        TaskStatus.DECLINED, TaskStatus.CANCELLED)


class FailureMode(str, Enum):
    """Why a task failed. Shared by TaskResult and the eval harness (design §10)."""
    LLM_FORMAT = "llm_format"
    TOOL_ERROR = "tool_error"
    TIMEOUT = "timeout"
    MAX_STEPS = "max_steps"
    MAX_ROUNDS = "max_rounds"
    WRONG_OUTPUT = "wrong_output"
    CRASH = "crash"


@dataclass
class Task:
    goal: str
    assignee: str                     # agent_id that executes it
    requester: str                    # ORCHESTRATOR, a worker id, or HUMAN (direct DM)
    session_id: str
    root_id: str                      # the human request this task belongs to
    origin_channel: str               # where the root request came from; decides visibility and HITL
    context: str = ""                 # call-specific notes; session progress comes from the board
    files: list[str] = field(default_factory=list)   # names copied into the assignee's inbox/
    chain: list[str] = field(default_factory=list)   # delegation chain, e.g. ["orchestrator", "coder"]
    parent_id: str | None = None
    status: TaskStatus = TaskStatus.ASSIGNED
    id: str = field(default_factory=lambda: "t" + uuid.uuid4().hex[:6])
    created_at: float = field(default_factory=time.time)

    @property
    def depth(self) -> int:
        """Delegation depth: 0 for a task issued by the Orchestrator or a human."""
        return max(len(self.chain) - 1, 0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Task:
        return cls(**{**d, "status": TaskStatus(d["status"])})


@dataclass
class TaskResult:
    task_id: str
    success: bool
    summary: str                      # the worker's final answer, <= result_summary_max_chars
    artifacts: list[str] = field(default_factory=list)      # files written, auto-filled from tool calls
    refs: dict[str, str] = field(default_factory=dict)      # commit hash, URLs, ...
    open_issues: list[str] = field(default_factory=list)    # unfinished items for the board
    error: str | None = None
    failure_mode: FailureMode | None = None
    declined: bool = False
    suggest: str | None = None        # when declined: the agent that fits better
    steps: int = 0
    duration: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TaskResult:
        fm = d.get("failure_mode")
        return cls(**{**d, "failure_mode": FailureMode(fm) if fm else None})
