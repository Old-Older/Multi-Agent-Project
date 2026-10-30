"""Message protocol shared by every component (design §3).

Owner: JIAN Yimin. Changes need agreement from both members.

Every payload is a plain JSON-serializable dict so messages can be logged and
persisted as-is. Use the TypedDicts below as the schema for each MsgType.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypedDict

HUMAN = "human"
ORCHESTRATOR = "orchestrator"
GROUP_MAIN = "group:main"


class MsgType(str, Enum):
    CHAT = "chat"                    # free text from a human or an agent
    TASK_ASSIGN = "task_assign"      # payload: TaskAssignPayload
    TASK_RESULT = "task_result"      # payload: TaskResultPayload, reply_to = the TASK_ASSIGN id
    HITL_REQUEST = "hitl_request"    # payload: HitlRequestPayload
    HITL_RESPONSE = "hitl_response"  # payload: HitlResponsePayload, reply_to = the HITL_REQUEST id
    STATUS = "status"                # payload: StatusPayload


@dataclass
class Message:
    type: MsgType
    sender: str                       # agent_id or HUMAN
    channel: str                      # GROUP_MAIN or dm_channel(a, b)
    content: str = ""                 # human-readable text shown in the chat
    payload: dict[str, Any] = field(default_factory=dict)
    receiver: str | None = None       # who must act on it; None = nobody in particular
    mentions: list[str] = field(default_factory=list)  # parsed @names in content
    reply_to: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: float = field(default_factory=time.time)


# ---- payload schemas -------------------------------------------------------

class TaskAssignPayload(TypedDict):
    task: dict[str, Any]              # Task.to_dict()


class TaskResultPayload(TypedDict):
    result: dict[str, Any]            # TaskResult.to_dict()


class HitlRequestPayload(TypedDict):
    request_id: str                   # short id shown to the human, e.g. "h1"
    task_id: str
    kind: str                         # HitlKind value
    question: str
    options: list[str]


class HitlResponsePayload(TypedDict):
    request_id: str
    answer: str


class StatusPayload(TypedDict):
    task_id: str
    status: str                       # TaskStatus value
    note: str
    public: bool                      # True = also shown in the chat channel


# ---- channel helpers -------------------------------------------------------

def dm_channel(a: str, b: str) -> str:
    """Private channel name; order-independent so dm(a, b) == dm(b, a)."""
    x, y = sorted((a, b))
    return f"dm:{x}:{y}"


def is_group(channel: str) -> bool:
    return channel.startswith("group:")


def dm_members(channel: str) -> tuple[str, str]:
    _, a, b = channel.split(":", 2)
    return a, b
