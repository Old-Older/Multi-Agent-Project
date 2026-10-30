"""Scripted LLM for tests and for developing without an API key."""
from __future__ import annotations

from collections.abc import Callable

from mas.llm.base import ChatMessage, FunctionSpec, LLMClient, LLMResponse

Responder = Callable[[list[ChatMessage], list[FunctionSpec] | None], LLMResponse]


class MockLLM(LLMClient):
    """Returns scripted responses in order, or delegates to a responder function.

    MockLLM([LLMResponse(text="", tool_calls=[ToolCall("1", "finish", {...})])])
    MockLLM(responder=lambda messages, tools: LLMResponse(text="ok"))
    """

    def __init__(self, script: list[LLMResponse] | None = None,
                 responder: Responder | None = None) -> None:
        self.script = list(script or [])
        self.responder = responder
        self.calls: list[tuple[list[ChatMessage], list[FunctionSpec] | None]] = []

    async def chat(self, messages: list[ChatMessage],
                   tools: list[FunctionSpec] | None = None,
                   temperature: float = 0.2) -> LLMResponse:
        self.calls.append((messages, tools))
        if self.script:
            return self.script.pop(0)
        if self.responder:
            return self.responder(messages, tools)
        raise RuntimeError("MockLLM ran out of scripted responses")
