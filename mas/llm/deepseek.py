"""DeepSeek client (OpenAI-compatible API).

The course allows DeepSeek as well as the HKGAI gateway. Both speak the same chat-completions
protocol, so this is HKGAIClient (retries, timeouts, tool-call repair, error handling) with
DeepSeek's endpoint and model as the defaults and its name in the error messages.
"""
from __future__ import annotations

from typing import Any

from mas.config import DEFAULT_DEEPSEEK_BASE_URL, DEFAULT_DEEPSEEK_MODEL
from mas.llm.hkgai import HKGAIClient


class DeepSeekClient(HKGAIClient):
    label = "DeepSeek"

    def __init__(self, api_key: str, base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
                 model: str = DEFAULT_DEEPSEEK_MODEL, timeout: float = 60.0,
                 max_retries: int = 3, thinking: str = "off") -> None:
        """thinking: "off" asks DeepSeek not to think (the agents call tools at every step, so a model that
        thinks first is slower, and the thinking text would have to be sent back with each later request);
        "default" sends nothing and leaves the choice to the service."""
        if thinking not in ("off", "default"):
            raise ValueError("thinking must be 'off' or 'default'")
        super().__init__(api_key, base_url, model, timeout, max_retries)
        self.thinking = thinking

    def _extra_request(self) -> dict[str, Any]:
        return {"extra_body": {"thinking": {"type": "disabled"}}} if self.thinking == "off" else {}


__all__ = ["DeepSeekClient"]
