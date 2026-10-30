"""LLM client contract (design §11).

Owner: LI Heyang.

Messages use the OpenAI chat format (list of {"role", "content", ...} dicts),
which the DeepSeek API accepts directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

ChatMessage = dict[str, Any]


@dataclass
class FunctionSpec:
    """A function the LLM may call. Built by Tool.spec() or by agents for virtual tools."""
    name: str
    description: str
    parameters: dict[str, Any]        # JSON Schema of the arguments

    def to_openai(self) -> dict[str, Any]:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.parameters}}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]         # already parsed and repaired; {} if unrecoverable
    raw_arguments: str = ""


@dataclass
class LLMResponse:
    text: str                         # may be non-empty alongside tool calls (Orchestrator plan line)
    tool_calls: list[ToolCall] = field(default_factory=list)  # may hold several -> run in parallel
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = ""


class LLMError(Exception):
    """Raised only after retries are exhausted."""


class LLMClient(ABC):
    @abstractmethod
    async def chat(self, messages: list[ChatMessage],
                   tools: list[FunctionSpec] | None = None,
                   temperature: float = 0.2) -> LLMResponse:
        """One completion. Handles timeout/rate-limit retries with backoff and
        repairs malformed tool-call JSON. Raises LLMError when it finally gives up."""
