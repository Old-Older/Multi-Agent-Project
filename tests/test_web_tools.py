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
        for failure in (response(status=429), response(status=402), httpx.ConnectError("down")):
            self.responses.append(failure)
            with self.assertLogs("mas.tools.web", level="WARNING"):
                result = await self.search(query="q", count=3, freshness="pw")
            self.assertTrue(result.ok, result.output)
            self.assertEqual(json.loads(result.output),
                             [{"title": "Found & kept", "url": "https://one.example/a", "description": "d"}])
        self.keyless.assert_called_with("q", 3, "pw")

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

    # A proxy that answers DNS itself hands out 198.18.x.x; that is refused unless the user opted in.
    async def test_the_benchmark_range_is_refused_by_default_and_allowed_on_request(self):
        self.records["one.example"] = ["198.18.0.46"]
        result = await FetchURL().run(self.sandbox, url="https://one.example/")
        self.assertFalse(result.ok)
        self.assertIn("publicly routable", result.output)
        self.assertEqual(self.requests, [])
        self.responses.append(response(b"<title>T</title><p>text</p>"))
        result = await FetchURL(allow_fake_ip=True).run(self.sandbox, url="https://one.example/")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(json.loads(result.output)["title"], "T")

    async def test_the_option_opens_only_that_range(self):
        for address in ("127.0.0.1", "10.0.0.8", "192.168.1.1", "169.254.169.254", "::1"):
            with self.subTest(address=address):
                self.records["one.example"] = [address]
                result = await FetchURL(allow_fake_ip=True).run(self.sandbox, url="https://one.example/")
                self.assertFalse(result.ok)
                self.assertIn("publicly routable", result.output)
        self.records["one.example"] = ["198.18.0.46", "10.0.0.8"]                  # one bad address among the allowed ones
        self.assertFalse((await FetchURL(allow_fake_ip=True).run(self.sandbox, url="https://one.example/")).ok)

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


class KeylessEnginesTest(unittest.TestCase):
    """The blocking helper that talks to ddgs, with ddgs replaced."""

    def run_with(self, behaviour, **kwargs):
        import sys
        import types

        calls = []

        class FakeDDGS:
            def __init__(self, **options):
                self.options = options

            def text(self, query, **options):
                calls.append((query, options))
                result = behaviour[options["backend"]]
                if isinstance(result, Exception):
                    raise result
                return result

        fake = types.ModuleType("ddgs")
        fake.DDGS = FakeDDGS
        with patch.dict(sys.modules, {"ddgs": fake}):
            from mas.tools.web import _keyless_text
            return _keyless_text("q", kwargs.get("count", 3), kwargs.get("freshness", "")), calls

    def test_the_next_engine_is_tried_when_one_fails_or_finds_nothing(self):
        row = {"title": "T", "href": "https://a.example", "body": "B"}
        rows, calls = self.run_with({"auto": RuntimeError("blocked"), "bing": [], "duckduckgo": [row]})
        self.assertEqual(rows, [{"title": "T", "url": "https://a.example", "description": "B"}])
        self.assertEqual([c[1]["backend"] for c in calls], ["auto", "bing", "duckduckgo"])
        self.assertTrue(all(c[1]["max_results"] == 3 for c in calls))

    def test_freshness_becomes_the_engines_time_limit(self):
        row = {"title": "T", "href": "https://a.example", "body": "B"}
        _, calls = self.run_with({"auto": [row]}, freshness="pm")
        self.assertEqual(calls[0][1]["timelimit"], "m")
        _, calls = self.run_with({"auto": [row]})
        self.assertNotIn("timelimit", calls[0][1])

    def test_every_engine_failing_is_one_clear_error(self):
        down = RuntimeError("down")
        with self.assertRaisesRegex(ValueError, "no search engine answered"):
            self.run_with({"auto": down, "bing": down, "duckduckgo": down, "brave": down, "yahoo": []})

    def test_a_missing_package_says_how_to_install_it(self):
        import sys
        with patch.dict(sys.modules, {"ddgs": None}):
            from mas.tools.web import _keyless_text
            with self.assertRaisesRegex(ValueError, "pip install ddgs"):
                _keyless_text("q", 3, "")
