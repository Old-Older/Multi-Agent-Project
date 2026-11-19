"""Web research tools.

web_search asks DeepSeek's own search API when the DeepSeek model is in use (its key goes only to the fixed DeepSeek
endpoint) and otherwise, or when that cannot answer (key rejected, balance used up, rate limit, server error), a keyless
search through DuckDuckGo and other engines (the `ddgs` package). The keyless path is what makes the system work on a
machine that has no search key. fetch_url reads the page from this machine; when a site refuses it (HTTP 401, 403, 406,
429, 451 or a server error), the same DeepSeek key lets DeepSeek's fetch API read the page from its side.
"""
from __future__ import annotations

import asyncio
import codecs
import html
import ipaddress
import json
import logging
import re
import socket
import time
import weakref
import zlib
from datetime import date, timedelta
from html.parser import HTMLParser
from typing import Any

import httpx

from mas.sandbox.base import Sandbox
from mas.tools.base import Tool, ToolResult


log = logging.getLogger(__name__)

_TIMEOUT = 20.0
_SEARCH_TIMEOUT = 20.0              # more than the keyless search's own deadline
_MAX_BYTES = 1_048_576
_FRESHNESS = ("pd", "pw", "pm", "py")
# DeepSeek's search API: one request, one answer in about a second; the query is at most 128 characters and takes
# operators (after:, lang:, site:). Fixed endpoint: the key is sent nowhere else.
_DEEPSEEK_SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
_DEEPSEEK_TIMEOUT = 8.0             # shorter than the whole search, so that a fallback still has time
_DEEPSEEK_QUERY_MAX = 128
_DEEPSEEK_DAYS = {"pd": 1, "pw": 7, "pm": 31, "py": 366}
_DEEPSEEK_TEXT_MAX = 360
_DEEPSEEK_FETCH_URL = "https://api.deepseek.com/v1/tools/fetch"
_DEEPSEEK_FETCH_TIMEOUT = 25.0      # some pages take it 15 s
_FETCH_WITH_FALLBACK_TIMEOUT = 40.0  # the whole fetch_url call: this machine's try, then DeepSeek's
# A site that refuses this machine (blocked, rate-limited, behind a login wall, or failing) may let DeepSeek's fetch in.
# A missing page (404, 410) is not retried: it is not there for DeepSeek either.
_REFUSED_STATUSES = {401, 403, 406, 429, 451}
_REDIRECTS = {301, 302, 303, 307, 308}
# The keyless search is a stop-gap for machines with no search key: one call to ddgs, whose "auto" mode already
# asks its own engines in parallel (naming one engine is not worth it: several, such as bing and google, are
# disabled in the library and silently turn into "auto" anyway). What matters is that it never holds a run up:
# a short deadline, and after a few failures in a row it stands down for a while, so a rate-limited network costs
# a run seconds, not minutes of retries. DeepSeek's search API (with the DeepSeek model) replaces all of this.
_KEYLESS_TIMEOUT = 8.0              # ddgs' own limit for one request
_KEYLESS_DEADLINE = 12.0            # the whole search
_KEYLESS_GIVE_UP_AFTER = 3          # failures in a row...
_KEYLESS_PAUSE = 30.0               # ...and then no attempts for this long
_keyless = {"failures": 0, "paused_until": 0.0}
_KEYLESS_TIMELIMIT = {"pd": "d", "pw": "w", "pm": "m", "py": "y"}

# Answers are kept for a while: agents repeat searches (retries, two members researching the same thing), and a
# repeated search is free. Only answers with results are kept, never failures.
_SEARCH_CACHE: dict[tuple[str, int, str], tuple[float, list[dict[str, str]]]] = {}
_SEARCH_CACHE_TTL = 1800.0
_KEYLESS_CONCURRENCY = 3                 # keyless searches at the same time: more than that only brings rate limits
_SEARCH_CACHE_SIZE = 256


_SLOTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = weakref.WeakKeyDictionary()


def _keyless_slot() -> asyncio.Semaphore:
    """Room for a keyless search: at most _KEYLESS_CONCURRENCY at a time in this event loop (members working in
    parallel would otherwise ask the search engines all at once and be refused)."""
    loop = asyncio.get_running_loop()
    slot = _SLOTS.get(loop)
    if slot is None:
        slot = _SLOTS[loop] = asyncio.Semaphore(_KEYLESS_CONCURRENCY)
    return slot


def _cached(key: tuple[str, int, str]) -> list[dict[str, str]] | None:
    hit = _SEARCH_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _SEARCH_CACHE_TTL:
        return [dict(row) for row in hit[1]]
    _SEARCH_CACHE.pop(key, None)
    return None


def _remember(key: tuple[str, int, str], rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    if len(_SEARCH_CACHE) >= _SEARCH_CACHE_SIZE:
        _SEARCH_CACHE.pop(min(_SEARCH_CACHE, key=lambda k: _SEARCH_CACHE[k][0]))
    _SEARCH_CACHE[key] = (time.monotonic(), [dict(row) for row in rows])


# Pages are kept the same way: two members reading the same page, or one member reading it again, cost one request.
_FETCH_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}
_FETCH_CACHE_SIZE = 128


def _fetch_cached(key: tuple[str, int]) -> dict | None:
    hit = _FETCH_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _SEARCH_CACHE_TTL:
        return dict(hit[1])
    _FETCH_CACHE.pop(key, None)
    return None


def _fetch_remember(key: tuple[str, int], page: dict) -> None:
    if _FETCH_CACHE_SIZE <= 0:
        return
    if len(_FETCH_CACHE) >= _FETCH_CACHE_SIZE:
        _FETCH_CACHE.pop(min(_FETCH_CACHE, key=lambda k: _FETCH_CACHE[k][0]))
    _FETCH_CACHE[key] = (time.monotonic(), dict(page))


class _SearchUnavailable(Exception):
    """DeepSeek's search or fetch could not answer (rejected key, no balance, rate limit, server or network trouble)."""


class _HttpStatus(ValueError):
    """A page answered with an HTTP error status."""

    def __init__(self, code: int) -> None:
        super().__init__(f"page returned HTTP {code}")
        self.code = code


def _keyless_failed() -> None:
    _keyless["failures"] += 1
    if _keyless["failures"] >= _KEYLESS_GIVE_UP_AFTER:
        _keyless["paused_until"] = time.monotonic() + _KEYLESS_PAUSE
        _keyless["failures"] = 0


_KEYLESS_ADVICE = ("Do not keep retrying: continue with fetch_url on pages you already know, or write up what you "
                   "have and say what is missing.")


def _keyless_text(query: str, count: int, freshness: str) -> list[dict[str, str]]:
    """Search without a key (ddgs, "auto"). Blocking: run it in a thread. Raises ValueError if it cannot answer."""
    try:
        from ddgs import DDGS
    except ImportError:
        raise ValueError("keyless search needs the 'ddgs' package: python -m pip install ddgs") from None
    if time.monotonic() < _keyless["paused_until"]:
        raise ValueError(f"search is paused for a moment: the free search engines have not been answering. {_KEYLESS_ADVICE}")
    options = {"timelimit": _KEYLESS_TIMELIMIT[freshness]} if freshness else {}
    try:
        rows = DDGS(timeout=_KEYLESS_TIMEOUT).text(query, max_results=count, backend="auto", **options)
    except Exception as exc:                             # ddgs raises its own types
        log.debug("keyless search failed: %s", type(exc).__name__)
        rows = []
    results = [{"title": str(r.get("title") or ""), "url": str(r.get("href") or ""),
                "description": str(r.get("body") or "")} for r in rows if isinstance(r, dict)]
    if not results:
        _keyless_failed()
        raise ValueError("no search results (the free search engines may be rate limiting this network). "
                         f"Rephrase once if you like. {_KEYLESS_ADVICE}")
    _keyless["failures"] = 0
    return results


def _check_key(key: object, name: str) -> None:
    """A key that cannot be sent as a header value is a mistake in the configuration: say so, never send it."""
    if not isinstance(key, str) or not key.isascii() or not key.isprintable() or " " in key:
        raise ValueError(f"invalid {name}")


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
    timeout = _TIMEOUT

    async def run(self, sandbox: Sandbox, **kwargs: Any) -> ToolResult:
        try:
            result = await asyncio.wait_for(self._request(**kwargs), timeout=self.timeout)
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
    timeout = _SEARCH_TIMEOUT
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

    def __init__(self, deepseek_key: str = "") -> None:
        self._deepseek_key = deepseek_key

    async def _request(self, *, query: str, count: int = 5, freshness: str = "") -> list[dict[str, str]]:
        if not isinstance(query, str) or not query.strip() or len(query) > 600 or len(query.split()) > 75:
            raise ValueError("query must contain 1 to 600 characters and at most 75 words")
        _integer(count, "count", 10)
        if freshness != "" and freshness not in _FRESHNESS:
            raise ValueError("freshness must be pd, pw, pm or py")
        key = (" ".join(query.lower().split()), count, freshness)
        if (hit := _cached(key)) is not None:
            return hit
        if self._deepseek_key:
            _check_key(self._deepseek_key, "DEEPSEEK_API_KEY")
            try:
                results = await self._deepseek(query, count, freshness)
                _remember(key, results)
                return results
            except _SearchUnavailable as exc:
                log.warning("DeepSeek search unavailable (%s); using the keyless search instead", exc)
        try:
            async with _keyless_slot():
                rows = await asyncio.wait_for(asyncio.to_thread(_keyless_text, query.strip(), count, freshness),
                                              _KEYLESS_DEADLINE)
        except asyncio.TimeoutError:
            _keyless_failed()                            # the thread finishes by itself; nobody waits for it
            raise ValueError(f"no search results within {_KEYLESS_DEADLINE:g} s. {_KEYLESS_ADVICE}") from None
        results = self._clean(rows, count)
        _remember(key, results)
        return results

    async def _deepseek(self, query: str, count: int, freshness: str) -> list[dict[str, str]]:
        """DeepSeek's search API. Raises _SearchUnavailable when it cannot answer (key rejected, no balance, rate limit,
        server or network trouble), so that the next search is tried."""
        text = " ".join(query.split())
        suffix = ""
        if freshness:                                       # DeepSeek has no freshness parameter: the after: operator does it
            suffix += f" after:{(date.today() - timedelta(days=_DEEPSEEK_DAYS[freshness])).isoformat()}"
        if text.isascii() and "lang:" not in text:         # an English question gets English pages first
            suffix += " lang:en"
        text = text[:_DEEPSEEK_QUERY_MAX - len(suffix)].rstrip() + suffix
        headers = {"Authorization": f"Bearer {self._deepseek_key}", "Content-Type": "application/json",
                   "Accept-Encoding": "gzip, identity"}
        try:
            async with httpx.AsyncClient(timeout=_DEEPSEEK_TIMEOUT) as client:
                async with client.stream("POST", _DEEPSEEK_SEARCH_URL, headers=headers, follow_redirects=False,
                                         json={"query": text, "count": count, "need_content": False}) as response:
                    if not response.is_success:
                        raise _SearchUnavailable(f"HTTP {response.status_code}")
                    body, truncated = await _bounded_body(response)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise _SearchUnavailable(type(exc).__name__) from None
        if truncated:
            raise ValueError("DeepSeek search response exceeded the byte limit")
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError) as exc:
            raise ValueError("invalid DeepSeek search JSON response") from exc
        rows = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("invalid DeepSeek search results")
        results = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("title"), str):
                continue
            try:
                _url(row.get("url"))
            except (ValueError, httpx.InvalidURL):
                continue
            results.append({"title": row["title"].strip(), "url": row["url"], "description": self._deepseek_text(row)})
            if len(results) == count:
                break
        return results

    @staticmethod
    def _deepseek_text(row: dict) -> str:
        """What the model reads about one result: the date and site, then the start of the summary (the longer text,
        without its repeated headline), or the snippet."""
        text = " ".join(str(row.get("summary") or row.get("snippet") or "").split())
        title = row["title"].strip()
        text = re.sub(r"^#+\s*", "", text)
        if text.startswith(title):
            text = text[len(title):].lstrip(" -—:.…")
        text = text[:_DEEPSEEK_TEXT_MAX].rstrip()
        when = row.get("date") if isinstance(row.get("date"), str) else ""
        site = row.get("site_name") if isinstance(row.get("site_name"), str) else ""
        meta = " · ".join(filter(None, [when[:10], site.strip()]))
        return f"[{meta}] {text}" if meta and text else meta and f"[{meta}]" or text

    @staticmethod
    def _clean(rows: list, count: int) -> list[dict[str, str]]:
        """Keep rows with a title and an http(s) URL, unescape the text, return at most `count`."""
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

    def __init__(self, deepseek_key: str = "") -> None:
        self._deepseek_key = deepseek_key
        if deepseek_key:
            self.timeout = _FETCH_WITH_FALLBACK_TIMEOUT

    async def _request(self, *, url: str, max_chars: int = 3000) -> dict[str, Any]:
        _integer(max_chars, "max_chars", 20000)
        source = _url(url)
        key = (str(source), max_chars)
        if (hit := _fetch_cached(key)) is not None:
            return hit
        try:
            page = await self._fetch(source, max_chars)
        except _HttpStatus as refused:
            if not self._deepseek_key or not (refused.code in _REFUSED_STATUSES or refused.code >= 500):
                raise
            _check_key(self._deepseek_key, "DEEPSEEK_API_KEY")
            try:
                page = await self._deepseek_page(source, max_chars)
            except _SearchUnavailable as exc:
                log.warning("DeepSeek fetch unavailable (%s); the page stays unread", exc)
                raise refused from None
            if page is None:                            # DeepSeek could not read it either: the first answer stands
                raise refused from None
        _fetch_remember(key, page)
        return page

    async def _deepseek_page(self, source: httpx.URL, max_chars: int) -> dict[str, Any] | None:
        """The page as DeepSeek's fetch API reads it (Markdown). None when it cannot read the page either (its answer says
        the page could not be fetched); _SearchUnavailable when the service itself cannot answer."""
        headers = {"Authorization": f"Bearer {self._deepseek_key}", "Content-Type": "application/json",
                   "Accept-Encoding": "gzip, identity"}
        try:
            async with httpx.AsyncClient(timeout=_DEEPSEEK_FETCH_TIMEOUT) as client:
                async with client.stream("POST", _DEEPSEEK_FETCH_URL, headers=headers, follow_redirects=False,
                                         json={"url": str(source)}) as response:
                    if response.status_code == 404:                 # "failed to fetch": the page is not readable from there
                        return None
                    if not response.is_success:
                        raise _SearchUnavailable(f"HTTP {response.status_code}")
                    body, truncated = await _bounded_body(response)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise _SearchUnavailable(type(exc).__name__) from None
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError):
            raise _SearchUnavailable("invalid answer") from None
        content = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(content, str) or not content.strip():
            return None
        title = payload.get("title") if isinstance(payload.get("title"), str) else ""
        content = content.strip()
        return {"url": str(source), "title": " ".join(title.split())[:300], "text": content[:max_chars],
                "truncated": truncated or len(content) > max_chars, "via": "deepseek"}

    async def _fetch(self, source: httpx.URL, max_chars: int) -> dict[str, Any]:
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
                                raise _HttpStatus(response.status_code)
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
