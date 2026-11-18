"""Offline HTTP-level tests; no credentials, DNS or servers are required."""
from __future__ import annotations

import asyncio
import codecs
import gzip
import json
import socket
import unittest
from unittest.mock import Mock, patch

import httpx

from mas.sandbox.base import Sandbox
from mas.tools.web import FetchURL, WebSearch


def response(body=b"", *, status=200, content_type="text/html", **headers):
    return httpx.Response(status, stream=httpx.ByteStream(body),
                          headers={"Content-Type": content_type, **headers})


class WebToolsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sandbox = Mock(spec=Sandbox)
        self.requests = []
        self.responses = []
        self.records = {"one.example": ["1.1.1.1"], "two.example": ["8.8.8.8"]}
        self.client_args = []
        client_class = httpx.AsyncClient

        def serve(request):
            self.requests.append(request)
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        def make_client(**kwargs):
            self.client_args.append(kwargs)
            return client_class(transport=httpx.MockTransport(serve), **kwargs)

        async def resolve(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                    for ip in self.records[host]]

        # No test may reach a real search engine: the keyless search is replaced, and fails unless a test says otherwise.
        from mas.tools import web
        web._SEARCH_CACHE.clear()
        web._FETCH_CACHE.clear()
        self.addCleanup(web._SEARCH_CACHE.clear)
        self.addCleanup(web._FETCH_CACHE.clear)
        # Most tests fetch one address again and again with different canned pages: the page cache is off unless a test turns it on.
        self.enter_patch(patch("mas.tools.web._FETCH_CACHE_SIZE", 0))
        self.keyless = Mock(side_effect=ValueError("no search engine answered"))
        self.enter_patch(patch("mas.tools.web._keyless_text", self.keyless))
        self.enter_patch(patch("mas.tools.web.httpx.AsyncClient", side_effect=make_client))
        self.enter_patch(patch.object(asyncio.get_running_loop(), "getaddrinfo", side_effect=resolve))

    def enter_patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    async def fetch(self, **kwargs):
        return await FetchURL().run(self.sandbox, **kwargs)

    async def search(self, **kwargs):
        return await WebSearch("test-token").run(self.sandbox, **kwargs)

    async def test_search_sends_provider_parameters_and_returns_original_source_urls(self):
        payload = {"web": {"results": [
            {"title": "Unsafe", "url": "file:///example"},
            {"title": "来源 &amp; evidence", "url": "https://one.example/article#detail",
             "description": "A &amp; B"},
            {"title": "Extra", "url": "https://two.example"},
        ]}}
        self.responses.append(response(json.dumps(payload).encode(), content_type="application/json"))
        result = await self.search(query=" 最近 新闻 ", count=1, freshness="pw")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(json.loads(result.output), [
            {"title": "来源 & evidence", "url": "https://one.example/article#detail", "description": "A & B"}])
        request, = self.requests
        self.assertEqual(request.url.host, "api.search.brave.com")
        self.assertEqual(request.url.path, "/res/v1/web/search")
        self.assertEqual(dict(request.url.params), {"q": "最近 新闻", "count": "1",
                                                   "freshness": "pw", "text_decorations": "false"})
        self.assertEqual(request.headers["x-subscription-token"], "test-token")
        self.assertNotIn("test-token", str(request.url))

    async def test_search_empty_or_malformed_response(self):
        for payload, valid in (({"type": "search"}, True), ({"web": {"results": []}}, True),
                               ({"web": {"results": "wrong"}}, False), ([], False), ({}, False)):
            with self.subTest(payload=payload):
                self.responses.append(response(json.dumps(payload).encode()))
                result = await self.search(query="topic")
                self.assertIs(result.ok, valid, result.output)
                if valid:
                    self.assertEqual(json.loads(result.output), [])
        self.responses.append(response(b"upstream failure"))
        self.assertFalse((await self.search(query="topic")).ok)

    async def test_search_configuration_and_model_arguments(self):
        for kwargs in ({}, {"query": " "}, {"query": 22}, {"query": "q", "count": True},
                       {"query": "q", "count": 11}, {"query": "q", "freshness": "soon"},
                       {"query": "q", "unexpected": True}):
            self.assertFalse((await self.search(**kwargs)).ok)
        self.assertEqual(self.requests, [])
        self.assertFalse((await WebSearch("bad key").run(self.sandbox, query="q")).ok)    # a key with a space
        self.keyless.assert_not_called()

    async def test_gzip_search_and_html_page(self):
        payload = {"web": {"results": [{"title": "News", "url": "https://one.example/story"}]}}
        self.responses.append(response(gzip.compress(json.dumps(payload).encode()),
                                       content_type="application/json", **{"Content-Encoding": "gzip"}))
        result = await self.search(query="news")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(json.loads(result.output)[0]["url"], "https://one.example/story")
        page = gzip.compress(b"<title>News</title>") + gzip.compress("<p>新进展</p>".encode())
        self.responses.append(response(page, **{"Content-Encoding": "gzip"}))
        result = await self.fetch(url="https://one.example")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(json.loads(result.output), {"url": "https://one.example", "title": "News",
                                                    "text": "新进展", "truncated": False})
        self.assertTrue(all(r.headers["accept-encoding"] == "gzip, identity" for r in self.requests))

    async def test_corrupt_or_incomplete_gzip_fails(self):
        valid = gzip.compress(b"page")
        for body in (b"not compressed", valid[:-1], valid + b"garbage", b""):
            with self.subTest(body=body):
                self.responses.append(response(body, **{"Content-Encoding": "gzip"}))
                result = await self.fetch(url="https://one.example")
                self.assertFalse(result.ok)
                self.assertIn("gzip", result.output)

    async def test_gzip_limits_both_transferred_and_decompressed_bytes(self):
        expanded = b"x" * 10000
        large_output = gzip.compress(expanded)
        large_input = gzip.compress(b"x" * 60, compresslevel=0)
        self.assertLess(len(large_output), 64)
        self.assertGreater(len(large_input), 64)
        with patch("mas.tools.web._MAX_BYTES", 64):
            for data in (large_output, large_input):
                with self.subTest(wire_bytes=len(data)):
                    for _ in range(2):
                        self.responses.append(response(data, content_type="text/plain",
                                                       **{"Content-Encoding": "gzip"}))
                    result = await self.fetch(url="https://one.example")
                    self.assertTrue(result.ok, result.output)
                    page = json.loads(result.output)
                    self.assertTrue(page["truncated"])
                    if data == large_output:
                        self.assertEqual(page["text"], "x" * 64)
                    else:
                        self.assertGreater(len(page["text"]), 0)
                        self.assertLess(len(page["text"]), 60)
                    result = await self.search(query="news")
                    self.assertFalse(result.ok)
                    self.assertIn("byte limit", result.output)

    async def test_provider_failures_do_not_disclose_the_key_or_follow_redirects(self):
        self.responses.extend([response(status=302, Location="https://two.example"),
                               response(b"test-token", status=429),
                               httpx.RemoteProtocolError("test-token")])
        for expected in ("HTTP 302", "HTTP 429", "RemoteProtocolError"):
            with self.assertLogs("mas.tools.web", level="WARNING") as logs:
                result = await self.search(query="q")              # the keyless search is down too in this test
            self.assertFalse(result.ok)
            self.assertIn(expected, logs.output[0])
            self.assertNotIn("test-token", result.output + "".join(logs.output))
        self.assertEqual([r.url.host for r in self.requests], ["api.search.brave.com"] * 3)

    async def test_when_brave_cannot_answer_the_keyless_search_does(self):
        self.keyless.side_effect = None
        self.keyless.return_value = [{"title": "Found &amp; kept", "url": "https://one.example/a", "description": "d"},
                                     {"title": "Unsafe", "url": "file:///etc/passwd", "description": ""}]
        for n, failure in enumerate((response(status=429), response(status=402), httpx.ConnectError("down"))):
            self.responses.append(failure)
            with self.assertLogs("mas.tools.web", level="WARNING"):
                result = await self.search(query=f"q{n}", count=3, freshness="pw")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(json.loads(result.output),
                             [{"title": "Found & kept", "url": "https://one.example/a", "description": "d"}])
        self.keyless.assert_called_with("q2", 3, "pw")

    async def test_a_repeated_search_is_answered_from_the_cache(self):
        payload = {"web": {"results": [{"title": "A", "url": "https://one.example/a", "description": "d"}]}}
        self.responses.append(response(json.dumps(payload).encode(), content_type="application/json"))
        first = await self.search(query="  Chip  Outlook ", count=2)
        again = await self.search(query="chip outlook", count=2)               # same words, other spacing and case
        self.assertEqual((first.ok, again.ok, again.output), (True, True, first.output))
        self.assertEqual(len(self.requests), 1)                                  # only the first one went out
        self.responses.append(response(json.dumps(payload).encode(), content_type="application/json"))
        await self.search(query="chip outlook", count=3)                         # another count: another search
        self.assertEqual(len(self.requests), 2)

    async def test_the_cache_keeps_results_not_failures_and_forgets_after_a_while(self):
        from mas.tools import web
        self.responses.extend([response(status=500), response(status=500)])
        self.keyless.side_effect = ValueError("no search engine answered")
        for _ in range(2):
            with self.assertLogs("mas.tools.web", level="WARNING"):
                self.assertFalse((await self.search(query="down")).ok)
        self.assertEqual(len(self.requests), 2)                                  # a failure is tried again
        self.assertEqual(web._SEARCH_CACHE, {})
        self.keyless.reset_mock()
        self.keyless.side_effect = None
        self.keyless.return_value = [{"title": "T", "url": "https://two.example", "description": ""}]
        await WebSearch("").run(self.sandbox, query="old")
        await WebSearch("").run(self.sandbox, query="old")
        self.assertEqual(self.keyless.call_count, 1)
        with patch("mas.tools.web.time.monotonic", return_value=web.time.monotonic() + web._SEARCH_CACHE_TTL + 1):
            await WebSearch("").run(self.sandbox, query="old")
        self.assertEqual(self.keyless.call_count, 2)                             # after the time limit it asks again

    async def test_a_cached_answer_cannot_be_changed_by_a_caller(self):
        self.keyless.side_effect = None
        self.keyless.return_value = [{"title": "T", "url": "https://two.example", "description": ""}]
        first = json.loads((await WebSearch("").run(self.sandbox, query="same")).output)
        first[0]["title"] = "changed"
        self.assertEqual(json.loads((await WebSearch("").run(self.sandbox, query="same")).output)[0]["title"], "T")

    async def test_a_bad_brave_answer_is_an_error_not_a_reason_to_search_elsewhere(self):
        self.responses.append(response(b"{not json"))
        result = await self.search(query="q")
        self.assertFalse(result.ok)
        self.keyless.assert_not_called()

    async def test_without_a_key_only_the_keyless_search_is_used(self):
        self.keyless.side_effect = None
        self.keyless.return_value = [{"title": "T", "url": "https://two.example", "description": "x"}]
        result = await WebSearch("").run(self.sandbox, query=" Public records ", count=2)
        self.assertTrue(result.ok, result.output)
        self.assertEqual(json.loads(result.output)[0]["url"], "https://two.example")
        self.keyless.assert_called_once_with("Public records", 2, "")
        self.assertEqual(self.requests, [])                           # nothing went to Brave

    async def test_when_no_engine_answers_the_error_says_what_to_do(self):
        result = await WebSearch("").run(self.sandbox, query="q")
        self.assertFalse(result.ok)
        self.assertIn("no search engine answered", result.output)

    async def test_fetch_redirects_to_the_final_source_and_pins_its_tls_hostname(self):
        page = ('<head><title>新闻 &amp; 研究</title><style>hidden</style></head>'
                '<body><h1>调查</h1><p>公开<em>研究</em>报告。</p><script>hidden</script></body>')
        self.responses.extend([response(status=301, Location="../updated"),
                               response(status=302, Location="https://two.example:8443/items"),
                               response(page.encode("gb18030"), content_type="text/html; charset=gb18030")])
        result = await self.fetch(url="https://one.example/archive/start#body")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(json.loads(result.output), {
            "url": "https://two.example:8443/items", "title": "新闻 & 研究",
            "text": "调查\n公开研究报告。", "truncated": False})
        self.assertEqual([r.url.host for r in self.requests], ["1.1.1.1", "1.1.1.1", "8.8.8.8"])
        self.assertEqual([r.url.path for r in self.requests], ["/archive/start", "/updated", "/items"])
        self.assertEqual(self.requests[-1].headers["Host"], "two.example:8443")
        self.assertEqual(self.requests[-1].extensions["sni_hostname"], "two.example")
        self.assertTrue(all(not args["trust_env"] for args in self.client_args))
        self.assertTrue(all("x-subscription-token" not in request.headers for request in self.requests))

    async def test_a_page_read_twice_is_fetched_once_and_a_failure_is_not_kept(self):
        from mas.tools import web
        with patch("mas.tools.web._FETCH_CACHE_SIZE", 8):
            self.responses.extend([response(status=500), response(b"<title>T</title><p>text</p>")])
            self.assertFalse((await self.fetch(url="https://one.example/p")).ok)          # a failure is tried again
            first = await self.fetch(url="https://one.example/p")
            again = await self.fetch(url="https://one.example/p")
            self.assertEqual((first.ok, again.output), (True, first.output))
            self.assertEqual(len(self.requests), 2)                                       # the failure and one good fetch
            self.responses.append(response(b"<title>T</title><p>text</p>"))
            await self.fetch(url="https://one.example/p", max_chars=50)                   # another length: another fetch
            self.assertEqual(len(self.requests), 3)
            self.assertEqual(len(web._FETCH_CACHE), 2)

    async def test_fetch_rejects_private_or_mixed_addresses_on_every_hop(self):
        for ip in ("127.0.0.1", "10.0.0.8", "169.254.169.254", "::1", "fec0::1",
                   "::ffff:192.168.1.1", "224.0.0.1"):
            with self.subTest(ip=ip):
                self.records["two.example"] = ["8.8.8.8", ip]
                self.responses.append(response(status=307, Location="//two.example/page"))
                before = len(self.requests)
                result = await self.fetch(url="https://one.example")
                self.assertFalse(result.ok)
                self.assertIn("publicly routable", result.output)
                self.assertEqual(len(self.requests), before + 1)

    async def test_fetch_invalid_arguments_and_schemes(self):
        for kwargs in ({}, {"url": "file:///test"}, {"url": "data:text/plain,abc"},
                       {"url": "https://user:password@one.example"}, {"url": "relative/file"},
                       {"url": 2}, {"url": "https://one.example", "max_chars": False},
                       {"url": "https://one.example", "max_chars": 0}, {"url": "x", "extra": 1}):
            with self.subTest(kwargs=kwargs):
                self.assertFalse((await self.fetch(**kwargs)).ok)
        self.assertEqual(self.requests, [])

    async def test_fetch_respects_body_and_character_limits_and_retains_newlines(self):
        self.responses.extend([response(b"abcdef", content_type="text/plain"),
                               response("a\nb\nc".encode(), content_type="text/plain")])
        with patch("mas.tools.web._MAX_BYTES", 4):
            first = await self.fetch(url="https://one.example", max_chars=10)
        self.assertEqual(json.loads(first.output)["text"], "abcd")
        self.assertTrue(json.loads(first.output)["truncated"])
        second = await self.fetch(url="https://one.example", max_chars=3)
        self.assertEqual(json.loads(second.output)["text"], "a\nb")
        self.assertTrue(json.loads(second.output)["truncated"])

    async def test_fetch_detects_html_charsets_and_reports_expected_failures(self):
        self.responses.append(response('<meta charset="gb18030"><p>中文</p>'.encode("gb18030")))
        self.assertEqual(json.loads((await self.fetch(url="https://one.example")).output)["text"], "中文")
        self.responses.extend([response(b"x", content_type="application/pdf"),
                               response(b"x", content_type="text/plain; charset=missing-codec"),
                               response(status=404), httpx.ReadTimeout("mock timeout")])
        for expected in ("text or HTML", "encoding", "404", "timed out"):
            result = await self.fetch(url="https://one.example")
            self.assertFalse(result.ok)
            self.assertIn(expected, result.output)

    async def test_fetch_uses_unicode_bom_before_http_or_html_charset(self):
        page = '<meta charset="ascii"><title>新闻</title><p>正文</p>'
        encodings = [
            (codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
            (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be"),
            (codecs.BOM_UTF8, "utf-8"),
        ]
        for marker, encoding in encodings:
            for content_type in ("text/html", "text/html; charset=ascii"):
                with self.subTest(encoding=encoding, content_type=content_type):
                    self.responses.append(response(marker + page.encode(encoding), content_type=content_type))
                    result = await self.fetch(url="https://one.example")
                    self.assertTrue(result.ok, result.output)
                    payload = json.loads(result.output)
                    self.assertEqual((payload["title"], payload["text"]), ("新闻", "正文"))

    async def test_redirect_loops_are_bounded_and_connections_try_next_address(self):
        self.responses.extend(response(status=301, Location="/loop") for _ in range(6))
        self.assertFalse((await self.fetch(url="https://one.example")).ok)
        self.records["two.example"] = ["1.1.1.1", "8.8.8.8"]
        self.responses.extend([httpx.ConnectError("unreachable"), response(b"page")])
        result = await self.fetch(url="https://two.example")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(self.requests[-1].url.host, "8.8.8.8")


class KeylessSearchTest(unittest.TestCase):
    """The blocking helper that talks to ddgs (replaced), and the rule that a dead search never holds a run up."""

    ROW = {"title": "T", "href": "https://a.example", "body": "B"}

    def setUp(self):
        from mas.tools import web
        web._keyless.update(failures=0, paused_until=0.0)
        self.addCleanup(web._keyless.update, failures=0, paused_until=0.0)

    def run_with(self, result, **kwargs):
        import sys
        import types

        calls = []

        class FakeDDGS:
            def __init__(self, **options):
                self.options = options

            def text(self, query, **options):
                calls.append((query, options))
                if isinstance(result, Exception):
                    raise result
                return result

        fake = types.ModuleType("ddgs")
        fake.DDGS = FakeDDGS
        with patch.dict(sys.modules, {"ddgs": fake}):
            from mas.tools.web import _keyless_text
            return _keyless_text("q", kwargs.get("count", 3), kwargs.get("freshness", "")), calls

    def test_one_call_in_auto_mode_and_the_rows_are_reshaped(self):
        rows, calls = self.run_with([self.ROW])
        self.assertEqual(rows, [{"title": "T", "url": "https://a.example", "description": "B"}])
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0][0], calls[0][1]["backend"], calls[0][1]["max_results"]), ("q", "auto", 3))

    def test_freshness_becomes_the_time_limit(self):
        _, calls = self.run_with([self.ROW], freshness="pm")
        self.assertEqual(calls[0][1]["timelimit"], "m")
        _, calls = self.run_with([self.ROW])
        self.assertNotIn("timelimit", calls[0][1])

    def test_no_results_and_errors_are_one_clear_message_that_says_what_to_do_instead(self):
        for result in ([], RuntimeError("blocked")):
            with self.subTest(result=result), self.assertRaisesRegex(ValueError, "no search results.*Do not keep retrying"):
                self.run_with(result)

    def test_after_three_failures_in_a_row_it_stands_down_without_asking_anybody(self):
        from mas.tools import web
        for _ in range(3):
            with self.assertRaises(ValueError):
                self.run_with(RuntimeError("blocked"))
        with self.assertRaisesRegex(ValueError, "paused for a moment"):
            _, calls = self.run_with([self.ROW])                       # even a working engine is not asked
        with patch("mas.tools.web.time.monotonic", return_value=web.time.monotonic() + web._KEYLESS_PAUSE + 1):
            rows, calls = self.run_with([self.ROW])                    # and it tries again after the pause
        self.assertEqual((len(rows), len(calls)), (1, 1))

    def test_a_success_resets_the_count(self):
        for _ in range(2):
            with self.assertRaises(ValueError):
                self.run_with(RuntimeError("blocked"))
        self.run_with([self.ROW])
        for _ in range(2):
            with self.assertRaises(ValueError):
                self.run_with(RuntimeError("blocked"))
        rows, _ = self.run_with([self.ROW])                            # still not paused: two, a success, two
        self.assertEqual(len(rows), 1)

    def test_a_missing_package_says_how_to_install_it(self):
        import sys
        with patch.dict(sys.modules, {"ddgs": None}):
            from mas.tools.web import _keyless_text
            with self.assertRaisesRegex(ValueError, "pip install ddgs"):
                _keyless_text("q", 3, "")


class KeylessDeadlineTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_search_that_hangs_ends_at_the_deadline_with_advice(self):
        import time

        from mas.tools import web
        web._keyless.update(failures=0, paused_until=0.0)
        self.addCleanup(web._keyless.update, failures=0, paused_until=0.0)
        web._SEARCH_CACHE.clear()
        self.addCleanup(web._SEARCH_CACHE.clear)

        def slow(query, count, freshness):
            time.sleep(1.5)
            return []
        started = time.monotonic()
        with patch("mas.tools.web._keyless_text", slow), patch("mas.tools.web._KEYLESS_DEADLINE", 0.2):
            result = await WebSearch("").run(Mock(spec=Sandbox), query="q")
        self.assertLess(time.monotonic() - started, 1.0)               # it did not wait for the thread
        self.assertFalse(result.ok)
        self.assertIn("Do not keep retrying", result.output)
        self.assertEqual(web._keyless["failures"], 1)                  # and counts as a failure
