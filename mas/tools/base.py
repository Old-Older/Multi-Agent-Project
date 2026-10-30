"""Tool contract (design §6).

Owner: LI Heyang.

Tool errors are returned as ToolResult(ok=False) and fed back to the LLM as an
observation; run() must not raise for expected failures.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from mas.llm.base import FunctionSpec
from mas.sandbox.base import Sandbox


@dataclass
class ToolResult:
    ok: bool
    output: str                       # observation text for the LLM (truncated by the worker)
    files_written: list[str] = field(default_factory=list)  # feeds TaskResult.artifacts
    refs: dict[str, str] = field(default_factory=dict)      # e.g. {"commit": "a1b2c3d"}


class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any]        # JSON Schema
    requires_approval: bool = False   # worker asks the human (HITL approval) before run()

    @abstractmethod
    async def run(self, sandbox: Sandbox, **kwargs: Any) -> ToolResult: ...

    def spec(self) -> FunctionSpec:
        return FunctionSpec(self.name, self.description, self.parameters)
