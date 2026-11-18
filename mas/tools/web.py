"""Web research tools. Search credentials go only to the fixed Brave API endpoint."""
from __future__ import annotations

import asyncio
import codecs
import html
import ipaddress
import json
import re
import socket
import zlib
from html.parser import HTMLParser
from typing import Any

import httpx

from mas.sandbox.base import Sandbox
from mas.tools.base import Tool, ToolResult


_TIMEOUT = 20.0
_MAX_BYTES = 1_048_576
_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_FRESHNESS = ("pd", "pw", "pm", "py")
_REDIRECTS = {301, 302, 303, 307, 308}


def _integer(value: int, name: str, maximum: int) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer from 1 to {maximum}")


def _url(value: str) -> httpx.URL:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("url must be a nonempty string")
    url = httpx.URL(value)
    if url.scheme not in ("http", "https") or not url.host or url.userinfo:
        raise ValueError("expected an absolute HTTP(S) URL without credentials")
    return url.copy_with(fragment=None)


async def _bounded_body(response: httpx.Response) -> tuple[bytes, bool]:
    encoding = response.headers.get("content-encoding", "identity").strip().lower()
    if encoding not in {"identity", "gzip"}:
        raise ValueError("server returned an unsupported content encoding")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
    body = bytearray()
    wire_remaining = _MAX_BYTES
    async for wire_chunk in response.aiter_raw(chunk_size=8192):
        wire_truncated = len(wire_chunk) > wire_remaining
        chunk = wire_chunk[:wire_remaining]
        wire_remaining -= len(chunk)
        if decoder is None:
            body.extend(chunk)
        else:
            # A gzip entity may contain several members. Bound output inside zlib
            # before it allocates memory, including when another member follows.
            while chunk:
                if decoder.eof:
                    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                remaining = _MAX_BYTES - len(body)
                try:
                    decoded = decoder.decompress(chunk, remaining + 1)
                except zlib.error as exc:
                    raise ValueError("invalid gzip data") from exc
                body.extend(decoded[:remaining])
                if len(decoded) > remaining:
                    return bytes(body), True
                chunk = decoder.unused_data
        if wire_truncated:
            return bytes(body), True
    if decoder is not None and not decoder.eof:
        raise ValueError("incomplete gzip data")
    return bytes(body), False


class _WebTool(Tool):
    async def run(self, sandbox: Sandbox, **kwargs: Any) -> ToolResult:
        try:
            result = await asyncio.wait_for(self._request(**kwargs), timeout=_TIMEOUT)
            return ToolResult(True, json.dumps(result, ensure_ascii=False))
        except (asyncio.TimeoutError, httpx.TimeoutException):
            return ToolResult(False, f"{self.name}: request timed out")
        except (httpx.RequestError, httpx.InvalidURL, OSError) as exc:
            # Transport exception text can include URLs or invalid header values.
            return ToolResult(False, f"{self.name}: {type(exc).__name__}")
        except (ValueError, TypeError) as exc:
            return ToolResult(False, f"{self.name}: {exc}")


class WebSearch(_WebTool):
    name = "web_search"
    description = "Search the web for titles, source URLs and snippets. Filter recent coverage with freshness."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 600},
            "count": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            "freshness": {"type": "string", "enum": list(_FRESHNESS),
                          "description": "Past day (pd), week (pw), month (pm), or year (py)."},
        },
        "required": ["query"], "additionalProperties": False,
    }

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    async def _request(self, *, query: str, count: int = 5, freshness: str = "") -> list[dict[str, str]]:
        if not isinstance(query, str) or not query.strip() or len(query) > 600 or len(query.split()) > 75:
            raise ValueError("query must contain 1 to 600 characters and at most 75 words")
        _integer(count, "count", 10)
        params = {"q": query.strip(), "count": str(count), "text_decorations": "false"}
        if freshness != "":
            if freshness not in _FRESHNESS:
                raise ValueError("freshness must be pd, pw, pm or py")
            params["freshness"] = freshness
        if not isinstance(self._api_key, str) or not self._api_key:
            raise ValueError("set SEARCH_API_KEY to a Brave Search API key")
        if not self._api_key.isascii() or not self._api_key.isprintable() or " " in self._api_key:
            raise ValueError("invalid SEARCH_API_KEY")

        headers = {"X-Subscription-Token": self._api_key, "Accept": "application/json",
                   "Accept-Encoding": "gzip, identity"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("GET", _SEARCH_URL, params=params, headers=headers,
                                     follow_redirects=False) as response:
                if not response.is_success:
                    raise ValueError(f"Brave Search returned HTTP {response.status_code}")
                body, truncated = await _bounded_body(response)
        if truncated:
            raise ValueError("Brave Search response exceeded the byte limit")
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError) as exc:
            raise ValueError("invalid Brave Search JSON response") from exc
        if not isinstance(payload, dict) or ("web" not in payload and payload.get("type") != "search"):
            raise ValueError("invalid Brave Search result object")
        web = payload.get("web", {})
        rows = web.get("results", []) if isinstance(web, dict) else None
        if not isinstance(rows, list):
            raise ValueError("invalid Brave Search results")

        results = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("title"), str):
                continue
            try:
                _url(row.get("url"))
            except (ValueError, httpx.InvalidURL):
                continue
            description = row.get("description")
            results.append({"title": html.unescape(row["title"]), "url": row["url"],
                            "description": html.unescape(description) if isinstance(description, str) else ""})
            if len(results) == count:
                break
        return results


class _PageText(HTMLParser):
    _skip = {"script", "style", "noscript", "template", "svg"}
    _blocks = {"p", "div", "br", "li", "article", "section", "tr", "td", "th",
               "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"}

    def __init__(self) -> None:
        super().__init__()
        self.hidden = 0
        self.in_title = False
        self.title: list[str] = []
        self.body: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._skip:
            self.hidden += 1
        elif tag == "title" and not self.hidden:
            self.in_title = True
        elif tag in self._blocks and not self.hidden:
            self.body.append("\n")

    def handle_endtag(self, tag):
        if tag in self._skip:
            self.hidden = max(0, self.hidden - 1)
        elif tag == "title":
            self.in_title = False
        elif tag in self._blocks and not self.hidden:
            self.body.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            (self.title if self.in_title else self.body).append(data)


async def _public_addresses(url: httpx.URL) -> list[str]:
    port = url.port or (443 if url.scheme == "https" else 80)
    records = await asyncio.get_running_loop().getaddrinfo(
        url.raw_host.decode("ascii"), port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses:
        raise ValueError("host has no addresses")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if isinstance(ip, ipaddress.IPv6Address):
            if ip.is_site_local:
                raise ValueError("fetch_url requires a publicly routable address")
            ip = ip.ipv4_mapped or ip
        if not ip.is_global or ip.is_multicast or ip.is_reserved or "%" in address:
            raise ValueError("fetch_url requires a publicly routable address")
    return addresses


class FetchURL(_WebTool):
    name = "fetch_url"
    description = "Read visible text from a public HTTP(S) page. Returns the final source URL, title and text."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "minLength": 1},
            "max_chars": {"type": "integer", "minimum": 1, "maximum": 20000, "default": 3000},
        },
        "required": ["url"], "additionalProperties": False,
    }

    async def _request(self, *, url: str, max_chars: int = 3000) -> dict[str, Any]:
        _integer(max_chars, "max_chars", 20000)
        source = _url(url)
        for hop in range(6):
            # A separate client per hop prevents virtual hosts on one IP sharing TLS sessions or cookies.
            async with httpx.AsyncClient(trust_env=False, timeout=_TIMEOUT) as client:
                addresses = await _public_addresses(source)
                for address in addresses:
                    headers = {"Host": source.netloc.decode("ascii"), "Accept-Encoding": "gzip, identity"}
                    extensions = {"sni_hostname": source.raw_host.decode("ascii")}
                    try:
                        # Connect to the validated IP. TLS and HTTP still authenticate the original hostname.
                        async with client.stream("GET", source.copy_with(host=address), headers=headers,
                                                 extensions=extensions, follow_redirects=False) as response:
                            if response.status_code in _REDIRECTS:
                                location = response.headers.get("location")
                                if not location or hop == 5:
                                    raise ValueError("missing redirect location or too many redirects")
                                source = _url(str(source.join(location)))
                            elif response.is_success:
                                return await self._read_page(response, source, max_chars)
                            else:
                                raise ValueError(f"page returned HTTP {response.status_code}")
                        break
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        if address == addresses[-1]:
                            raise
        raise ValueError("too many redirects")

    @staticmethod
    async def _read_page(response: httpx.Response, source: httpx.URL, max_chars: int) -> dict[str, Any]:
        mime = response.headers.get("content-type", "").partition(";")[0].strip().lower()
        is_html = mime in {"text/html", "application/xhtml+xml"}
        if not is_html and not (mime.startswith("text/") or mime in {"application/json", "application/xml"}):
            raise ValueError("expected a text or HTML page")
        body, truncated = await _bounded_body(response)
        encoding = response.charset_encoding
        # UTF-32 LE starts with the UTF-16 LE marker; check the longer BOM first.
        if body.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            encoding = "utf-32"
        elif body.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            encoding = "utf-16"
        elif body.startswith(codecs.BOM_UTF8):
            encoding = "utf-8-sig"
        elif is_html and not encoding:
            match = re.search(rb"""<meta\s+[^>]*?charset\s*=\s*["']?([\w.-]+)""", body[:1024], re.I)
            if match:
                encoding = match[1].decode("ascii")
        try:
            text = body.decode(encoding or "utf-8", errors="replace")
        except LookupError as exc:
            raise ValueError("unknown page character encoding") from exc
        title = ""
        if is_html:
            parser = _PageText()
            try:
                parser.feed(text)
                parser.close()
            except AssertionError as exc:
                raise ValueError("invalid HTML markup") from exc
            title = " ".join("".join(parser.title).split())[:300]
            lines = (" ".join(line.split()) for line in "".join(parser.body).splitlines())
            text = "\n".join(line for line in lines if line)
        return {"url": str(source), "title": title, "text": text[:max_chars],
                "truncated": truncated or len(text) > max_chars}
