"""Which search web_search uses (DeepSeek's own with the DeepSeek model, the course's key with HKGAI) and how."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import unittest
from datetime import date
from unittest.mock import Mock, patch

import httpx

from mas.app import build_tools
from mas.agents.roles import RoleConfig
from mas.config import Settings
from mas.sandbox.base import Sandbox
from mas.tools import web
from mas.tools.web import WebSearch
from tests.test_web_tools import response

DS = "ds-secret-key"
BRAVE = "brave-secret-key"


def result_row(**fields):
    return {"title": "Nvidia at 12 Times Earnings", "url": "https://one.example/a", "site_name": "AInvest",
            "date": "2026-11-16T10:00:00+00:00", "authority": 3, "rerank_score": 2.5, "content": "",
            "snippet": "short snippet", "summary": "# Nvidia at 12 Times Earnings\n\nForward P/E is 12x on 2027 EPS.",
            **fields}


class WhichKeyTest(unittest.TestCase):
    def creds(self, llm, provider="auto", deepseek=DS, search=BRAVE):
        return Settings(llm_provider=llm, search_provider=provider, deepseek_api_key=deepseek,
                        search_api_key=search).search_credentials()

    def test_with_the_deepseek_model_the_search_is_deepseeks_own(self):
        self.assertEqual(self.creds("deepseek"), (DS, BRAVE))                 # the search key stays as the fallback
        self.assertEqual(self.creds("deepseek", search=""), (DS, ""))

    def test_with_the_hkgai_model_it_is_the_course_search_key_and_never_the_deepseek_key(self):
        self.assertEqual(self.creds("hkgai"), ("", BRAVE))
        self.assertEqual(self.creds("hkgai", search=""), ("", ""))             # nothing: the keyless search
        self.assertEqual(self.creds("hkgai", deepseek=""), ("", BRAVE))

    def test_without_a_deepseek_key_there_is_nothing_to_use(self):
        self.assertEqual(self.creds("deepseek", deepseek="", search=""), ("", ""))

    def test_the_setting_can_force_one(self):
        self.assertEqual(self.creds("hkgai", "deepseek"), (DS, BRAVE))
        self.assertEqual(self.creds("deepseek", "key"), ("", BRAVE))
        self.assertEqual(self.creds("deepseek", "keyless"), ("", ""))
        self.assertEqual(self.creds("hkgai", "keyless"), ("", ""))

    def test_a_setting_that_makes_no_sense_is_refused(self):
        with self.assertRaises(ValueError):
            Settings(search_provider="google")

    def test_the_environment_can_choose(self):
        with patch.dict(os.environ, {"SEARCH_PROVIDER": "keyless"}, clear=True):
            self.assertEqual(Settings.from_env().search_provider, "keyless")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings.from_env().search_provider, "auto")

    def test_the_tool_is_built_with_the_keys_the_rule_allows(self):
        role = RoleConfig("r", "R", "researches", "", ["web_search"])
        for llm, expected in (("deepseek", {"api_key": BRAVE, "deepseek_key": DS}),
                              ("hkgai", {"api_key": BRAVE, "deepseek_key": ""})):
            with patch.object(WebSearch, "__init__", return_value=None) as construct:
                build_tools(role, Settings(llm_provider=llm, deepseek_api_key=DS, search_api_key=BRAVE))
            construct.assert_called_once_with(**expected)


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

    async def search(self, deepseek=DS, brave="", **kwargs):
        return await WebSearch(api_key=brave, deepseek_key=deepseek).run(self.sandbox, **kwargs)

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

    async def test_when_deepseek_cannot_answer_the_next_search_does_and_the_key_goes_nowhere_else(self):
        brave_answer = {"web": {"results": [{"title": "From Brave", "url": "https://two.example/b", "description": "d"}]}}
        for n, failure in enumerate((response(status=401), response(status=402), response(status=429),
                                     response(status=500), httpx.ConnectError("down"))):
            self.responses.append(failure)
            self.responses.append(response(json.dumps(brave_answer).encode(), content_type="application/json"))
            with self.assertLogs("mas.tools.web", level="WARNING") as logs:
                result = await self.search(query=f"q{n}", brave=BRAVE)
            self.assertEqual(json.loads(result.output)[0]["title"], "From Brave", result.output)
            self.assertNotIn(DS, "".join(logs.output) + result.output)
            self.assertEqual([r.url.host for r in self.requests[-2:]], ["api.deepseek.com", "api.search.brave.com"])
            self.assertNotIn(DS, str(self.requests[-1].headers) + str(self.requests[-1].url))
            self.assertNotIn(BRAVE, str(self.requests[-2].headers) + str(self.requests[-2].url))

    async def test_without_a_search_key_it_falls_to_the_keyless_search(self):
        self.keyless.side_effect = None
        self.keyless.return_value = [{"title": "Keyless", "url": "https://one.example/k", "description": "d"}]
        self.responses.append(response(status=429))
        with self.assertLogs("mas.tools.web", level="WARNING"):
            result = await self.search(query="q")
        self.assertEqual(json.loads(result.output)[0]["title"], "Keyless")
        self.keyless.assert_called_once()

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


if __name__ == "__main__":
    unittest.main()
