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
        result = await WebSearch("").run(self.sandbox, query="Public records")
        self.assertFalse(result.ok)
        self.assertIn("SEARCH_API_KEY", result.output)
        for kwargs in ({}, {"query": " "}, {"query": 22}, {"query": "q", "count": True},
                       {"query": "q", "count": 11}, {"query": "q", "freshness": "soon"},
                       {"query": "q", "unexpected": True}):
            self.assertFalse((await self.search(**kwargs)).ok)
        self.assertEqual(self.requests, [])

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
        for expected in ("302", "429", "RemoteProtocolError"):
            result = await self.search(query="q")
            self.assertFalse(result.ok)
            self.assertIn(expected, result.output)
            self.assertNotIn("test-token", result.output)
        self.assertEqual([r.url.host for r in self.requests], ["api.search.brave.com"] * 3)

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
