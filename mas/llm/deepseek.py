"""DeepSeek client (OpenAI-compatible API).

Owner: LI Heyang.
"""
from __future__ import annotations

from mas.llm.base import ChatMessage, FunctionSpec, LLMClient, LLMResponse


class DeepSeekClient(LLMClient):
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com",
                 model: str = "deepseek-chat", timeout: float = 60.0,
                 max_retries: int = 3) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    async def chat(self, messages: list[ChatMessage],
                   tools: list[FunctionSpec] | None = None,
                   temperature: float = 0.2) -> LLMResponse:
        raise NotImplementedError
