"""HKGAI client (OpenAI-compatible API).

Owner: LI Heyang.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI

from mas.config import DEFAULT_HKGAI_BASE_URL, DEFAULT_HKGAI_MODEL
from mas.llm.base import ChatMessage, FunctionSpec, LLMClient, LLMError, LLMResponse, ToolCall


def _finite_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def _arguments(raw: str) -> dict[str, Any]:
    """Recover fenced JSON and trailing commas; never evaluate model-supplied code."""
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        first, _, rest = text.partition("\n")
        if first.strip().lower() in {"```", "```json"}:
            text = rest[:-3].strip()

    # A JSON decoder identifies the error outside quoted strings, so contents of
    # paths, code snippets and other argument strings are preserved verbatim.
    for _ in range(9):
        try:
            value = json.loads(text, parse_float=_finite_float, parse_constant=_finite_float)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError as error:
            if text[error.pos:error.pos + 1] == ",":
                # Python 3.14 points at the trailing comma itself; older versions point at the bracket.
                if text[error.pos + 1:].lstrip()[:1] not in ("}", "]"):
                    return {}
                text = text[:error.pos] + text[error.pos + 1:]
                continue
            prefix = text[:error.pos].rstrip()
            if text[error.pos:error.pos + 1] not in ("}", "]") or not prefix.endswith(","):
                return {}
            text = prefix[:-1] + text[error.pos:]
        except (RecursionError, ValueError):
            return {}
    return {}


def _response(completion: Any, label: str = "HKGAI") -> LLMResponse:
    """Check fields the SDK may leave unvalidated on an HTTP 200 response."""
    try:
        choice = completion.choices[0]
        message = choice.message
        content = message.content
        if message.role != "assistant" or (content is not None and not isinstance(content, str)):
            raise ValueError
        calls = []
        call_ids = set()
        for entry in message.tool_calls or []:
            call_id, name, raw = entry.id, entry.function.name, entry.function.arguments
            if (entry.type != "function" or not isinstance(call_id, str) or not call_id.strip()
                    or call_id in call_ids or not isinstance(name, str) or not name.strip()
                    or not isinstance(raw, str)):
                raise ValueError
            call_ids.add(call_id)
            calls.append(ToolCall(call_id, name, _arguments(raw), raw))
        reason = choice.finish_reason
        if not isinstance(reason, str) or (reason == "tool_calls" and not calls):
            raise ValueError
        usage = dict(completion.usage) if completion.usage is not None else {}
        counts = {key: value for key, value in usage.items() if type(value) is int}
        return LLMResponse(content or "", calls, counts, reason)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        raise LLMError(f"{label} returned an invalid chat completion") from None


def _retry_after(header: str | None) -> float:
    """HTTP Retry-After can be a number of seconds or a GMT date."""
    if not header:
        return 0.0
    try:
        delay = float(header)
    except ValueError:
        try:
            delay = parsedate_to_datetime(header).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError, OSError):
            return 0.0
    return max(0.0, delay) if math.isfinite(delay) else 0.0


class HKGAIClient(LLMClient):
    """Any OpenAI-compatible chat endpoint; `label` only names the provider in error messages.
    DeepSeekClient (mas/llm/deepseek.py) is this class with DeepSeek's defaults."""

    label = "HKGAI"

    def __init__(self, api_key: str, base_url: str = DEFAULT_HKGAI_BASE_URL,
                 model: str = DEFAULT_HKGAI_MODEL, timeout: float = 60.0,
                 max_retries: int = 3) -> None:
        if not api_key.strip() or not model.strip():
            raise ValueError(f"{self.label} API key, base URL and model are required")
        try:
            if not isinstance(base_url, str):
                raise ValueError
            url = urlsplit(base_url)
            if (url.scheme not in {"http", "https"} or not url.hostname or url.query or url.fragment
                    or url.username is not None or url.port == 0
                    or any(char.isspace() for char in url.netloc)):
                raise ValueError
            # The SDK transport also checks IDNA and rejects control characters.
            httpx.URL(base_url)
        except (httpx.InvalidURL, ValueError):
            # Parser diagnostics can contain embedded credentials or invalid port text.
            raise ValueError(f"{self.label} base URL must be an absolute HTTP(S) URL "
                             "without credentials, query or fragment, and with a valid port") from None
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") + "/v1" if url.path in ("", "/") else base_url
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    async def chat(self, messages: list[ChatMessage],
                   tools: list[FunctionSpec] | None = None,
                   temperature: float = 0.2) -> LLMResponse:
        request: dict[str, Any] = {
            "messages": messages, "model": self.model, "temperature": temperature,
        }
        if tools:
            request["tools"] = [tool.to_openai() for tool in tools]

        # A chat owns its transport, including on cancellation. There is no
        # process-wide client or second layer of SDK retries to keep track of.
        async with AsyncOpenAI(api_key=self.api_key, base_url=self.base_url,
                               timeout=self.timeout, max_retries=0) as client:
            for attempt in range(self.max_retries + 1):
                delay = 0.5 * 2 ** min(attempt, 4)
                try:
                    completion = await asyncio.wait_for(
                        client.chat.completions.create(**request), timeout=self.timeout)
                    return _response(completion, self.label)
                except (asyncio.TimeoutError, APITimeoutError):
                    failure = "request timed out"
                except APIConnectionError:
                    failure = "connection failed"
                except APIStatusError as error:
                    failure = f"HTTP {error.status_code}"
                    if error.code in ("invalid_request", "convert_request_failed", "too_many_failed_keys",
                                      "model_not_found", "do_request_failed"):
                        raise LLMError(f"{self.label} {failure} ({error.code})") from None
                    if error.status_code not in {408, 409, 429} and error.status_code < 500:
                        raise LLMError(f"{self.label} {failure}") from None
                    wait = _retry_after(error.response.headers.get("Retry-After"))
                    if wait > self.timeout:
                        raise LLMError(f"{self.label} {failure}: Retry-After exceeds the configured timeout") from None
                    delay = max(delay, wait)
                except (APIError, ValueError, RecursionError):
                    raise LLMError(f"{self.label} returned an invalid chat completion") from None

                if attempt == self.max_retries:
                    raise LLMError(f"{self.label} {failure} after {attempt + 1} attempt(s)")
                await asyncio.sleep(delay)
