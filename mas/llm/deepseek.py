"""DeepSeek client (OpenAI-compatible API).

The course allows DeepSeek as well as the HKGAI gateway. Both speak the same chat-completions
protocol, so this is HKGAIClient (retries, timeouts, tool-call repair, error handling) with
DeepSeek's endpoint and model as the defaults and its name in the error messages.
"""
from __future__ import annotations

from mas.config import DEFAULT_DEEPSEEK_BASE_URL, DEFAULT_DEEPSEEK_MODEL
from mas.llm.hkgai import HKGAIClient


class DeepSeekClient(HKGAIClient):
    label = "DeepSeek"

    def __init__(self, api_key: str, base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
                 model: str = DEFAULT_DEEPSEEK_MODEL, timeout: float = 60.0,
                 max_retries: int = 3) -> None:
        super().__init__(api_key, base_url, model, timeout, max_retries)


__all__ = ["DeepSeekClient"]
