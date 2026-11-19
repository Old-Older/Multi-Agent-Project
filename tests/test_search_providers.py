"""What web_search and fetch_url may use besides this machine: DeepSeek's own search and fetch with the DeepSeek model,
nothing keyed with the HKGAI model; and how they are used."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import unittest
from datetime import date
from unittest.mock import Mock, patch

import httpx

from mas.agents.roles import RoleConfig
from mas.app import build_tools
from mas.config import Settings
from mas.sandbox.base import Sandbox
from mas.tools import web
from mas.tools.web import FetchURL, WebSearch
from tests.test_web_tools import response

DS = "ds-secret-key"


def result_row(**fields):
    return {"title": "Nvidia at 12 Times Earnings", "url": "https://one.example/a", "site_name": "AInvest",
            "date": "2026-11-16T10:00:00+00:00", "authority": 3, "rerank_score": 2.5, "content": "",
            "snippet": "short snippet", "summary": "# Nvidia at 12 Times Earnings\n\nForward P/E is 12x on 2027 EPS.",
            **fields}


class WhichKeyTest(unittest.TestCase):
    def key(self, llm, provider="auto", deepseek=DS):
        return Settings(llm_provider=llm, search_provider=provider, deepseek_api_key=deepseek).deepseek_search_key()

    def test_with_the_deepseek_model_search_and_fetch_may_use_deepseeks_own(self):
        self.assertEqual(self.key("deepseek"), DS)
        self.assertEqual(self.key("deepseek", deepseek=""), "")

    def test_with_the_hkgai_model_the_deepseek_key_is_never_used(self):
        self.assertEqual(self.key("hkgai"), "")

    def test_the_setting_can_force_one(self):
        self.assertEqual(self.key("hkgai", "deepseek"), DS)
        self.assertEqual(self.key("deepseek", "keyless"), "")
        self.assertEqual(self.key("hkgai", "keyless"), "")

    def test_a_setting_that_makes_no_sense_is_refused(self):
        for bad in ("google", "key", "brave"):
            with self.assertRaises(ValueError):
                Settings(search_provider=bad)

    def test_the_environment_can_choose(self):
        with patch.dict(os.environ, {"SEARCH_PROVIDER": "keyless"}, clear=True):
            self.assertEqual(Settings.from_env().search_provider, "keyless")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings.from_env().search_provider, "auto")

    def test_the_tools_are_built_with_the_key_the_rule_allows(self):
        role = RoleConfig("r", "R", "researches", "", ["web_search", "fetch_url"])
        for llm, expected in (("deepseek", DS), ("hkgai", "")):
            search, fetch = build_tools(role, Settings(llm_provider=llm, deepseek_api_key=DS))
            self.assertEqual((search._deepseek_key, fetch._deepseek_key), (expected, expected), llm)


class DeepSeekSearchTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sandbox = Mock(spec=Sandbox)
        self.requests, self.responses = [], []
        client_class = httpx.AsyncClient

        def serve(request):
            self.requests.append(request)
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        def make_client(**kwargs):
            return client_class(transport=httpx.MockTransport(serve), **kwargs)

        web._SEARCH_CACHE.clear()
        self.addCleanup(web._SEARCH_CACHE.clear)
        self.keyless = Mock(side_effect=ValueError("no search engine answered"))
        for patcher in (patch("mas.tools.web._keyless_text", self.keyless),
                        patch("mas.tools.web.httpx.AsyncClient", side_effect=make_client)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def answer(self, *rows, status=200):
        self.responses.append(response(json.dumps({"results": list(rows)}).encode(), status=status,
                                       content_type="application/json"))

    async def search(self, deepseek=DS, **kwargs):
        return await WebSearch(deepseek_key=deepseek).run(self.sandbox, **kwargs)

    async def test_the_request_goes_to_deepseek_only_with_the_key_in_a_header(self):
        self.answer(result_row())
        result = await self.search(query="Nvidia forward P/E", count=3)
        self.assertTrue(result.ok, result.output)
        request, = self.requests
        self.assertEqual((request.url.host, request.url.path, request.method), ("api.deepseek.com", "/v1/tools/search", "POST"))
        self.assertEqual(request.headers["authorization"], f"Bearer {DS}")
        self.assertEqual(json.loads(request.content), {"query": "Nvidia forward P/E lang:en", "count": 3, "need_content": False})
        self.assertNotIn(DS, str(request.url) + result.output)

    async def test_what_the_model_reads_is_the_date_the_site_and_the_summary_without_its_headline(self):
        self.answer(result_row(), result_row(title="No summary", url="https://two.example/b", summary="",
                                             snippet="  only   a snippet ", date=None, site_name=""),
                    {"title": "Unsafe", "url": "file:///etc/passwd"}, {"url": "https://x.example"},
                    result_row(title="Extra", url="https://three.example/c"))
        result = await self.search(query="topic", count=2)
        self.assertEqual(json.loads(result.output), [
            {"title": "Nvidia at 12 Times Earnings", "url": "https://one.example/a",
             "description": "[2026-11-16 · AInvest] Forward P/E is 12x on 2027 EPS."},
            {"title": "No summary", "url": "https://two.example/b", "description": "only a snippet"}])

    async def test_a_long_summary_is_cut(self):
        self.answer(result_row(summary="word " * 400))
        description = json.loads((await self.search(query="topic")).output)[0]["description"]
        self.assertLessEqual(len(description), web._DEEPSEEK_TEXT_MAX + 40)

    async def test_freshness_becomes_an_after_operator(self):
        with patch("mas.tools.web.date") as today:
            today.today.return_value = date(2026, 11, 19)
            for freshness, since in (("pd", "2026-11-18"), ("pw", "2026-11-12"), ("pm", "2026-10-19"), ("py", "2025-11-18")):
                self.answer(result_row())
                await self.search(query=f"chip news {freshness}", freshness=freshness)
                query = json.loads(self.requests[-1].content)["query"]
                self.assertEqual(query, f"chip news {freshness} after:{since} lang:en")

    async def test_the_query_is_cut_to_128_characters_with_the_operators_kept(self):
        self.answer(result_row())
        await self.search(query="supercalifragilistic " * 20, freshness="pw")      # 400 characters
        query = json.loads(self.requests[0].content)["query"]
        self.assertLessEqual(len(query), 128)
        self.assertTrue(query.endswith(" lang:en"))
        self.assertIn(" after:", query)

    async def test_the_language_operator_is_added_only_to_an_english_query_without_one(self):
        for text, sent in (("半導體 市場 預測", "半導體 市場 預測"), ("chip lang:fr", "chip lang:fr"), ("chip", "chip lang:en")):
            self.answer(result_row())
            await self.search(query=text)
            self.assertEqual(json.loads(self.requests[-1].content)["query"], sent)

    async def test_when_deepseek_cannot_answer_the_keyless_search_does_and_the_key_is_not_disclosed(self):
        self.keyless.side_effect = None
        self.keyless.return_value = [{"title": "Keyless", "url": "https://one.example/k", "description": "d"}]
        for n, failure in enumerate((response(status=401), response(status=402), response(status=429),
                                     response(status=500), httpx.ConnectError("down"))):
            self.responses.append(failure)
            with self.assertLogs("mas.tools.web", level="WARNING") as logs:
                result = await self.search(query=f"q{n}")
            self.assertEqual(json.loads(result.output)[0]["title"], "Keyless", result.output)
            self.assertNotIn(DS, "".join(logs.output) + result.output)
            self.assertEqual(self.requests[-1].url.host, "api.deepseek.com")
        self.assertEqual(self.keyless.call_count, 5)

    async def test_an_empty_answer_is_an_answer_and_a_bad_one_is_an_error(self):
        self.answer()
        result = await self.search(query="very specific")
        self.assertEqual((result.ok, json.loads(result.output)), (True, []))
        self.keyless.assert_not_called()
        for body in (b"not json", b"[]", b'{"results": "wrong"}', b"{}"):
            self.responses.append(response(body, content_type="application/json"))
            self.assertFalse((await self.search(query=f"q{body!r}")).ok)
        self.keyless.assert_not_called()                                         # an error, not a reason to ask elsewhere

    async def test_a_key_that_cannot_be_a_header_value_is_refused_and_not_sent(self):
        for key in ("bad key", "bad\nkey", "clé"):
            result = await self.search(deepseek=key, query="q")
            self.assertFalse(result.ok)
            self.assertIn("invalid DEEPSEEK_API_KEY", result.output)
        self.assertEqual(self.requests, [])

    async def test_a_repeated_search_is_answered_from_the_cache(self):
        self.answer(result_row())
        first = await self.search(query="Chip   Outlook")
        again = await self.search(query="chip outlook")
        self.assertEqual(first.output, again.output)
        self.assertEqual(len(self.requests), 1)

    async def test_no_deepseek_key_means_no_request_to_deepseek(self):
        self.keyless.side_effect = None
        self.keyless.return_value = [{"title": "K", "url": "https://one.example/k", "description": ""}]
        result = await self.search(deepseek="", query="q")
        self.assertTrue(result.ok)
        self.assertEqual(self.requests, [])


class DeepSeekFetchTest(unittest.IsolatedAsyncioTestCase):
    """fetch_url reads the page from this machine; a site that refuses it is tried through DeepSeek's fetch API."""

    PAGE = "https://one.example/report"

    async def asyncSetUp(self):
        self.sandbox = Mock(spec=Sandbox)
        self.requests, self.responses = [], []
        self.records = {"one.example": ["1.1.1.1"], "private.example": ["10.0.0.5"]}
        client_class = httpx.AsyncClient

        def serve(request):
            self.requests.append(request)
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        def make_client(**kwargs):
            return client_class(transport=httpx.MockTransport(serve), **kwargs)

        async def resolve(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in self.records[host]]

        web._FETCH_CACHE.clear()
        self.addCleanup(web._FETCH_CACHE.clear)
        for patcher in (patch("mas.tools.web.httpx.AsyncClient", side_effect=make_client),
                        patch.object(asyncio.get_running_loop(), "getaddrinfo", side_effect=resolve)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def deepseek_page(self, content="# Valuation\n\nForward P/E 12.1x", title="Key statistics", status=200):
        body = json.dumps({"title": title, "content": content}).encode()
        self.responses.append(response(body, status=status, content_type="application/json"))

    async def fetch(self, key=DS, **kwargs):
        return await FetchURL(deepseek_key=key).run(self.sandbox, url=kwargs.pop("url", self.PAGE), **kwargs)

    def hosts(self):
        return [r.headers.get("host") or r.url.host for r in self.requests]

    async def test_a_page_that_loads_here_is_not_sent_to_deepseek(self):
        self.responses.append(response(b"<title>T</title><p>text</p>"))
        result = await self.fetch()
        self.assertTrue(result.ok, result.output)
        self.assertEqual(json.loads(result.output)["text"], "text")
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn("api.deepseek.com", str(self.requests[0].headers.get("host")))

    async def test_a_page_the_site_refuses_is_read_through_deepseek(self):
        self.responses.append(response(status=403))
        self.deepseek_page()
        result = await self.fetch()
        self.assertTrue(result.ok, result.output)
        self.assertEqual(json.loads(result.output), {"url": self.PAGE, "title": "Key statistics",
                                                    "text": "# Valuation\n\nForward P/E 12.1x",
                                                    "truncated": False, "via": "deepseek"})
        request = self.requests[1]
        self.assertEqual((request.url.host, request.url.path, request.method), ("api.deepseek.com", "/v1/tools/fetch", "POST"))
        self.assertEqual(request.headers["authorization"], f"Bearer {DS}")
        self.assertEqual(json.loads(request.content), {"url": self.PAGE})
        self.assertNotIn(DS, result.output)

    async def test_which_refusals_are_retried_through_deepseek(self):
        for code in (401, 403, 406, 429, 451, 500, 503):
            web._FETCH_CACHE.clear()
            self.responses.append(response(status=code))
            self.deepseek_page(content=f"page after {code}")
            result = await self.fetch()
            self.assertTrue(result.ok, f"{code}: {result.output}")
            self.assertEqual(json.loads(result.output)["via"], "deepseek")
        for code in (404, 410, 400):
            web._FETCH_CACHE.clear()
            before = len(self.requests)
            self.responses.append(response(status=code))
            result = await self.fetch()
            self.assertFalse(result.ok)
            self.assertIn(f"HTTP {code}", result.output)
            self.assertEqual(len(self.requests), before + 1)                    # not tried through DeepSeek: it is not there

    async def test_when_deepseek_cannot_read_it_either_the_first_answer_stands(self):
        for failure in (response(b'{"error": {"message": "failed to fetch"}}', status=404), response(status=401),
                        response(status=402), response(status=429), response(status=500), httpx.ConnectError("down"),
                        response(b"not json"), response(b'{"title": "t", "content": "  "}'), response(b"[]")):
            web._FETCH_CACHE.clear()
            self.responses.extend([response(status=403), failure])
            result = await self.fetch()
            self.assertFalse(result.ok)
            self.assertIn("page returned HTTP 403", result.output)
            self.assertNotIn(DS, result.output)

    async def test_without_a_key_nothing_goes_to_deepseek(self):
        self.responses.append(response(status=403))
        result = await self.fetch(key="")
        self.assertFalse(result.ok)
        self.assertIn("HTTP 403", result.output)
        self.assertEqual(len(self.requests), 1)

    async def test_other_failures_are_not_sent_to_deepseek(self):
        result = await self.fetch(url="https://private.example/x")                  # an address this machine refuses
        self.assertFalse(result.ok)
        self.assertEqual(self.requests, [])
        self.responses.append(response(b"%PDF", content_type="application/pdf"))
        result = await self.fetch(url="https://one.example/file.pdf")               # not a text page
        self.assertFalse(result.ok)
        self.assertEqual(len(self.requests), 1)

    async def test_the_page_is_cut_to_max_chars_and_cached(self):
        self.responses.append(response(status=403))
        self.deepseek_page(content="x" * 500)
        result = await self.fetch(max_chars=100)
        page = json.loads(result.output)
        self.assertEqual((len(page["text"]), page["truncated"]), (100, True))
        again = await self.fetch(max_chars=100)
        self.assertEqual(again.output, result.output)
        self.assertEqual(len(self.requests), 2)                                     # one try here, one through DeepSeek

    async def test_a_bad_key_is_refused_before_anything_is_sent_to_deepseek(self):
        self.responses.append(response(status=403))
        result = await self.fetch(key="bad key")
        self.assertFalse(result.ok)
        self.assertIn("invalid DEEPSEEK_API_KEY", result.output)
        self.assertEqual(len(self.requests), 1)

    def test_a_fetch_that_may_go_through_deepseek_is_given_the_time_for_it(self):
        self.assertEqual(FetchURL().timeout, web._TIMEOUT)
        self.assertEqual(FetchURL(deepseek_key=DS).timeout, web._FETCH_WITH_FALLBACK_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
