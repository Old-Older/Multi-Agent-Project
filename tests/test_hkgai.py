"""HKGAI contract tests against an in-process HTTP transport."""
import asyncio
import json
import unittest
from functools import partial
from unittest.mock import AsyncMock, call, patch

import httpx
from openai import AsyncOpenAI

from mas.llm.base import FunctionSpec, LLMError, LLMResponse
from mas.llm.hkgai import HKGAIClient


def completion(content="done", calls=None, usage=None):
    message = {"role": "assistant", "content": content}
    if calls is not None:
        message["tool_calls"] = calls
    return {"id": "response", "model": "example-model", "object": "chat.completion",
            "created": 1, "choices": [{"index": 0, "message": message,
                                      "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": usage}


def tool_call(identifier, raw):
    return {"type": "function", "id": identifier,
            "function": {"name": "lookup", "arguments": raw}}


class HKGAITests(unittest.IsolatedAsyncioTestCase):
    messages = [{"role": "user", "content": "你好"}]

    def transport(self, handler, **settings):
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(http.aclose)
        factory = partial(AsyncOpenAI, http_client=http)
        mocked = self.enter_patch(patch("mas.llm.hkgai.AsyncOpenAI", side_effect=factory))
        client = HKGAIClient("test-value", "https://provider.invalid/v1", "example-model",
                                **settings)
        return client, http, mocked

    def enter_patch(self, patcher):
        self.addCleanup(patcher.stop)
        return patcher.start()

    async def test_request_format_and_mixed_response(self):
        raw = '```json\n{"query": "字,}", "items": [true, null,],}\n```'
        calls = [tool_call("first", raw), tool_call("second", '{"nested": {"score": 1.25}}')]
        spec = FunctionSpec("lookup", "Search", {"type": "object"})
        counts = {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11,
                  "cached_tokens": 3}

        def handler(request):
            self.assertEqual(str(request.url), "https://provider.invalid/v1/chat/completions")
            self.assertEqual(request.headers["authorization"], "Bearer test-value")
            self.assertEqual(json.loads(request.content),
                             {"messages": self.messages, "temperature": 0.15, "model": "example-model",
                              "tools": [spec.to_openai()]})
            usage = {**counts, "prompt_tokens_details": {"cached_tokens": 3}}
            return httpx.Response(200, json=completion("计划", calls, usage))

        client, http, factory = self.transport(handler)
        response = await client.chat(self.messages, [spec], 0.15)
        self.assertTrue(http.is_closed)
        self.assertEqual(factory.call_args.kwargs["max_retries"], 0)
        self.assertEqual((response.text, response.finish_reason, response.usage),
                         ("计划", "tool_calls", counts))
        self.assertEqual([(c.id, c.name) for c in response.tool_calls],
                         [("first", "lookup"), ("second", "lookup")])
        self.assertEqual(response.tool_calls[0].arguments, {"query": "字,}", "items": [True, None]})
        self.assertEqual(response.tool_calls[0].raw_arguments, raw)
        self.assertEqual(response.tool_calls[1].arguments, {"nested": {"score": 1.25}})

    async def test_text_without_tools_or_usage(self):
        def handler(request):
            self.assertNotIn("tools", json.loads(request.content))
            return httpx.Response(200, json=completion("纯文本"))

        client, _, _ = self.transport(handler)
        self.assertEqual(await client.chat(self.messages, []),
                         LLMResponse(text="纯文本", finish_reason="stop"))

    async def test_irrecoverable_arguments_keep_raw_and_remain_separate(self):
        invalid = ["[]", "null", "", '{"x":}', '{"x":NaN}', '{"x":1e999}',
                   '{"x":1} extra', 'dict(value="no evaluation")']
        calls = [tool_call(str(i), raw) for i, raw in enumerate(invalid)]
        client, _, _ = self.transport(lambda request: httpx.Response(
            200, json=completion(None, calls)))
        response = await client.chat(self.messages)
        self.assertEqual(response.text, "")
        self.assertEqual([c.arguments for c in response.tool_calls], [{} for _ in invalid])
        self.assertEqual([c.raw_arguments for c in response.tool_calls], invalid)

    async def test_connection_timeout_rate_limit_and_server_error_recover(self):
        errors = iter([httpx.ConnectError("private details"), httpx.ReadTimeout("private details"),
                       429, 503, 200])

        def handler(request):
            step = next(errors)
            if isinstance(step, Exception):
                raise step
            return httpx.Response(step, json=completion())

        client, _, _ = self.transport(handler, max_retries=4)
        with patch("mas.llm.hkgai.asyncio.sleep", new_callable=AsyncMock) as sleep:
            self.assertEqual((await client.chat(self.messages)).text, "done")
            self.assertEqual(sleep.await_args_list, [call(0.5), call(1.0), call(2.0), call(4.0)])

    async def test_retry_exhaustion_and_permanent_errors_omit_private_response(self):
        for status, attempts in [(429, 3), (500, 3), (401, 1), (400, 1)]:
            with self.subTest(status=status):
                requests = []

                def handler(request):
                    requests.append(request)
                    return httpx.Response(status, json={"error": {"message": "test-value private"}})

                client, http, _ = self.transport(handler, max_retries=2)
                with patch("mas.llm.hkgai.asyncio.sleep", new_callable=AsyncMock), \
                        self.assertRaisesRegex(LLMError, str(status)) as raised:
                    await client.chat(self.messages)
                self.assertNotIn("test-value", str(raised.exception))
                self.assertNotIn("private", str(raised.exception))
                self.assertEqual(len(requests), attempts)
                self.assertTrue(http.is_closed)

    async def test_respects_retry_after_without_an_unbounded_sleep(self):
        for header, retry in [("7", True), ("120", False)]:
            with self.subTest(header=header):
                responses = iter([httpx.Response(429, headers={"Retry-After": header}),
                                  httpx.Response(200, json=completion())])
                client, _, _ = self.transport(lambda _: next(responses), timeout=20)
                with patch("mas.llm.hkgai.asyncio.sleep", new_callable=AsyncMock) as sleep:
                    if retry:
                        self.assertEqual((await client.chat(self.messages)).text, "done")
                        sleep.assert_awaited_once_with(7)
                    else:
                        with self.assertRaisesRegex(LLMError, "Retry-After"):
                            await client.chat(self.messages)
                        sleep.assert_not_awaited()

    async def test_hkgai_request_error_returned_as_http_500_is_not_retried(self):
        response = httpx.Response(500, json={"error": {"code": "convert_request_failed",
                                                       "message": "private diagnostic"}})
        client, _, _ = self.transport(lambda _: response)
        with patch("mas.llm.hkgai.asyncio.sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaisesRegex(LLMError, "HTTP 500 .*convert_request_failed") as raised:
                await client.chat(self.messages)
            sleep.assert_not_awaited()
        self.assertNotIn("private", str(raised.exception))

    async def test_timeout_cancels_pending_request(self):
        stopped = asyncio.Event()

        async def handler(request):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        client, http, _ = self.transport(handler, timeout=0.1, max_retries=0)
        with self.assertRaisesRegex(LLMError, "timed out"):
            await client.chat(self.messages)
        self.assertTrue(stopped.is_set())
        self.assertTrue(http.is_closed)

    async def test_caller_cancellation_propagates_and_closes_transport(self):
        started = asyncio.Event()

        async def handler(request):
            started.set()
            await asyncio.Event().wait()

        client, http, _ = self.transport(handler)
        task = asyncio.create_task(client.chat(self.messages))
        await asyncio.wait_for(started.wait(), 15)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(http.is_closed)

    async def test_corrupt_response_raises_llm_error(self):
        errors = [httpx.Response(200, text="not a completion"),
                  httpx.Response(200, content=b"{oops", headers={"Content-Type": "application/json"}),
                  httpx.Response(200, json={"choices": []}),
                  httpx.Response(200, json=completion(None, [tool_call("x", "{}"),
                                                            tool_call("x", "{}")])),
                  httpx.Response(200, json=completion(None, [tool_call("", "{}")]))]
        for response in errors:
            with self.subTest(response=response.text):
                client, _, _ = self.transport(lambda request: response, max_retries=0)
                with self.assertRaisesRegex(LLMError, "invalid chat completion"):
                    await client.chat(self.messages)

    def test_invalid_limits(self):
        for options in ({"timeout": 0}, {"timeout": float("nan")}, {"max_retries": -1},
                        {"max_retries": 1.1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                HKGAIClient("example", **options)

    def test_configured_base_url_rejects_invalid_authority_without_echoing_it(self):
        for url in ("provider.invalid/v1", "ftp://provider.invalid", "https:///v1",
                    "https://name:private@provider.invalid", "https://provider.invalid:private",
                    "https://provider.invalid:65536", "https://provider.invalid:0",
                    "https://[unclosed", "https://bad host", "http://example.\u200d/",
                    "https://provider.invalid?key=private", "https://provider.invalid/#fragment",
                    "https://provider.invalid/a\nb"):
            with self.subTest(url=url), self.assertRaises(ValueError) as raised:
                HKGAIClient("unused", base_url=url)
            self.assertEqual(str(raised.exception), "HKGAI base URL must be an absolute HTTP(S) URL "
                             "without credentials, query or fragment, and with a valid port")
        for url in ("http://127.0.0.1:8080/v1", "http://[::1]:8080/v1", "https://mock.invalid/api/chat"):
            with self.subTest(url=url):
                self.assertEqual(HKGAIClient("unused", base_url=url).base_url, url)
        for url in ("https://api1.hkgai.net", "https://api1.hkgai.net/"):
            with self.subTest(url=url):
                self.assertEqual(HKGAIClient("unused", base_url=url).base_url, "https://api1.hkgai.net/v1")


class DeepSeekClientTests(unittest.IsolatedAsyncioTestCase):
    """DeepSeek is the same protocol; only the defaults and the name in messages differ."""

    def test_defaults_and_validation_messages_name_deepseek(self):
        from mas.llm.deepseek import DeepSeekClient
        client = DeepSeekClient("key")
        self.assertEqual((client.model, client.base_url), ("deepseek-chat", "https://api.deepseek.com/v1"))
        with self.assertRaisesRegex(ValueError, "^DeepSeek API key"):
            DeepSeekClient(" ")
        with self.assertRaisesRegex(ValueError, "^DeepSeek base URL must be"):
            DeepSeekClient("key", base_url="not a url")

    async def test_errors_say_deepseek_and_a_normal_reply_works(self):
        from mas.llm.base import LLMError
        from mas.llm.deepseek import DeepSeekClient

        for status, expect in ((200, None), (401, "DeepSeek HTTP 401")):
            def handler(request, status=status):
                if status == 200:
                    return httpx.Response(200, json=completion("ok", None, {"prompt_tokens": 1}))
                return httpx.Response(status, json={"error": {"message": "x"}})
            http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            self.addAsyncCleanup(http.aclose)
            with patch("mas.llm.hkgai.AsyncOpenAI", side_effect=partial(AsyncOpenAI, http_client=http)):
                client = DeepSeekClient("key", "https://provider.invalid/v1", "deepseek-chat", max_retries=0)
                if expect is None:
                    self.assertEqual((await client.chat([{"role": "user", "content": "hi"}])).text, "ok")
                else:
                    with self.assertRaisesRegex(LLMError, expect):
                        await client.chat([{"role": "user", "content": "hi"}])
