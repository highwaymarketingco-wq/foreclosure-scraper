"""The `client` a verifier's verify(row, client) receives.

Fetcher       live: http_client.get_text (its per-host throttle, retries, curl fallback and
              optional Chrome-TLS impersonation) plus an extra per-host minimum spacing for a
              long background sweep (VERIFY_HOST_MIN_INTERVAL_S, default 2.0 s), request
              counts per host, and optional capture of every response body to a directory
              (the sweep's --capture-dir; that is how test fixtures are recorded).

PACING GROUPS (2026-10-08). Hosts of one vendor that are one backend share ONE spacing slot
(SHARED_BACKENDS): every <tenant>.qpaybill.com county portal is the same PUBLIQ / Springbrook
service, and on 2026-10-08 at 18:34-18:35 UTC all of them answered 503 or the generic error page
in the same minute (Clarendon on its FIRST request of the run), so the vendor is paced as one
host: at most one request every min_interval_s across all its tenants, one at a time.
ReplayFetcher tests: answers from a {url: body | Exception} map and records what was asked,
              so a verifier is tested against real captured responses with no network.

FORM SESSIONS (added 2026-10-06 for the Buncombe Register of Deeds, an ASP.NET WebForms search
that keeps its search context in a server-side session): `async with client.form_session() as s`
gives a cookie session with `s.get(url)` and `s.post_form(url, data)`, each returning a
FormResponse(status, url, text) and never raising on an HTTP status, so the verifier can tell a
login redirect or a 403/429 block from a page. Same per-host pacing, request counts and capture
as get_text; a POST is captured and replayed under form_key(url, data), a hash of the posted
fields. The session is a plain cookie jar: no token is ever obtained, solved or forged.

Neither one ever solves a CAPTCHA or logs in. A verifier for a walled source does not fetch.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


#: vendor domains whose tenant hosts are one backend: paced as ONE host (module doc, PACING GROUPS)
SHARED_BACKENDS = ("qpaybill.com",)
DEFAULT_MIN_INTERVAL_S = 2.0


def pace_key(host: str) -> str:
    """The pacing slot of a host: its vendor domain for a SHARED_BACKENDS tenant, else itself."""
    h = (host or "").lower()
    for dom in SHARED_BACKENDS:
        if h == dom or h.endswith("." + dom):
            return dom
    return h


#: response headers a form-session caller may need (a 503 / 429 names when to come back)
_KEEP_HEADERS = ("retry-after",)


@dataclass
class FormResponse:
    status: int
    url: str            # the final URL after redirects
    text: str
    headers: dict = field(default_factory=dict)   # only _KEEP_HEADERS, lowercased names


def form_key(url: str, data: dict) -> str:
    """The capture/replay key of a POST: the URL plus a hash of the posted fields (sorted)."""
    body = urlencode(sorted((str(k), str(v)) for k, v in (data or {}).items()))
    return f"POST {url} #{hashlib.sha256(body.encode()).hexdigest()[:16]}"


class _LiveFormSession:
    """One curl_cffi cookie session (Chrome TLS, as rod/aumentum.py uses for the same vendor),
    paced and counted by its Fetcher."""

    def __init__(self, fetcher: "Fetcher", *, impersonate: str, verify: bool) -> None:
        self._f = fetcher
        self._imp, self._verify = impersonate, verify
        self._s: Any = None

    async def __aenter__(self) -> "_LiveFormSession":
        from curl_cffi.requests import AsyncSession   # lazy: only a form verifier needs it
        self._s = AsyncSession(verify=self._verify, impersonate=self._imp)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._s is not None:
            try:
                await self._s.close()
            except Exception:  # noqa: BLE001
                pass

    async def _go(self, method: str, url: str, key: str, **kw: Any) -> FormResponse:
        host = _host(url)
        await self._f._pace(host)
        self._f.requests[host] += 1
        try:
            r = await (self._s.get(url, **kw) if method == "GET" else self._s.post(url, **kw))
        except Exception:
            self._f.errors[host] += 1
            raise
        try:
            hdrs = {k: str(r.headers.get(k)) for k in _KEEP_HEADERS if r.headers.get(k)}
        except Exception:  # noqa: BLE001 - headers are evidence only
            hdrs = {}
        resp = FormResponse(status=int(r.status_code), url=str(r.url), text=r.text or "",
                            headers=hdrs)
        if resp.status >= 400:
            self._f.errors[host] += 1
        self._f._capture(key, resp.text, meta={"status": resp.status, "url": resp.url})
        return resp

    async def get(self, url: str, *, timeout: Optional[float] = None) -> FormResponse:
        return await self._go("GET", url, url, allow_redirects=True,
                              timeout=timeout or self._f.timeout)

    async def post_form(self, url: str, data: dict, *, headers: Optional[dict] = None,
                        timeout: Optional[float] = None) -> FormResponse:
        return await self._go("POST", url, form_key(url, data), data=data,
                              headers=headers or {}, allow_redirects=True,
                              timeout=timeout or max(self._f.timeout, 60.0))


class _ReplayFormSession:
    """Serves a ReplayFetcher's recordings: GET by URL, POST by form_key(url, data). A recorded
    value is the body text (status 200, url as asked), a dict {"status", "url", "text"}, or an
    Exception to raise. A missing recording raises LookupError like get_text."""

    def __init__(self, fetcher: "ReplayFetcher") -> None:
        self._f = fetcher

    async def __aenter__(self) -> "_ReplayFormSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def _answer(self, key: str, url: str) -> FormResponse:
        self._f.asked.append(key)
        if key not in self._f.responses:
            raise LookupError(f"no recorded response for {key}")
        v = self._f.responses[key]
        if isinstance(v, BaseException):
            raise v
        if isinstance(v, dict):
            return FormResponse(status=int(v.get("status", 200)), url=str(v.get("url") or url),
                                text=str(v.get("text") or ""),
                                headers={str(k).lower(): str(x)
                                         for k, x in (v.get("headers") or {}).items()})
        return FormResponse(status=200, url=url, text=str(v))

    async def get(self, url: str, **_: Any) -> FormResponse:
        return self._answer(url, url)

    async def post_form(self, url: str, data: dict, **_: Any) -> FormResponse:
        return self._answer(form_key(url, data), url)


class Fetcher:
    def __init__(self, *, min_interval_s: Optional[float] = None, timeout: float = 25.0,
                 capture_dir: Optional[Path | str] = None) -> None:
        self.min_interval_s = float(os.environ.get("VERIFY_HOST_MIN_INTERVAL_S",
                                                   str(DEFAULT_MIN_INTERVAL_S))
                                    if min_interval_s is None else min_interval_s)
        self.timeout = timeout
        self.capture_dir = Path(capture_dir) if capture_dir else None
        self.requests: Counter = Counter()
        self.errors: Counter = Counter()
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _pace(self, host: str) -> None:
        """Wait until min_interval_s has passed since the last request to this host's pacing slot
        (pace_key: one slot per SHARED_BACKENDS vendor), one caller at a time per slot."""
        key = pace_key(host)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            wait = self.min_interval_s - (time.monotonic() - self._last.get(key, 0.0))
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[key] = time.monotonic()

    async def get_text(self, url: str, *, timeout: Optional[float] = None,
                       impersonate: bool = False, headers: Optional[dict] = None) -> str:
        from ..http_client import get_text   # lazy: the network stack only when fetching
        host = _host(url)
        await self._pace(host)
        self.requests[host] += 1
        try:
            text = await get_text(url, timeout=timeout or self.timeout, headers=headers,
                                  impersonate=impersonate)
        except Exception:
            self.errors[host] += 1
            raise
        self._capture(url, text)
        return text

    async def get_json(self, url: str, **kw: Any) -> Any:
        return json.loads(await self.get_text(url, **kw))

    def form_session(self, *, impersonate: str = "chrome", verify: bool = False):
        """A cookie session for a WebForms search (see FORM SESSIONS above); use it as
        `async with client.form_session() as s:`. verify=False and Chrome TLS mirror
        rod/aumentum.py, the production client of the same vendor (the Buncombe ROD chain)."""
        return _LiveFormSession(self, impersonate=impersonate, verify=verify)

    def _capture(self, url: str, text: str, meta: Optional[dict] = None) -> None:
        """Save one response body. `url` is the URL, or form_key() for a POST; a form-session
        response also records its status and final URL as a JSON third column of index.tsv."""
        if not self.capture_dir:
            return
        try:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            real = url.split(" ")[1] if url.startswith("POST ") else url
            slug = re.sub(r"[^A-Za-z0-9]+", "_", urlsplit(real).path).strip("_")[-80:]
            h = hashlib.sha256(url.encode()).hexdigest()[:8]
            name = f"{_host(real)}__{slug}__{h}.html"
            (self.capture_dir / name).write_text(text, encoding="utf-8")
            with open(self.capture_dir / "index.tsv", "a", encoding="utf-8") as fh:
                extra = f"\t{json.dumps(meta, sort_keys=True)}" if meta else ""
                fh.write(f"{name}\t{url}{extra}\n")
        except OSError:
            pass

    def stats(self) -> dict:
        return {"requests": dict(self.requests), "errors": dict(self.errors)}


class ReplayFetcher:
    """Serves recorded responses. A URL with no recording raises LookupError, which a
    verifier must turn into an `unconfirmed` result like any other fetch failure."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = dict(responses)
        self.asked: list[str] = []

    async def get_text(self, url: str, **_: Any) -> str:
        self.asked.append(url)
        if url not in self.responses:
            raise LookupError(f"no recorded response for {url}")
        body = self.responses[url]
        if isinstance(body, BaseException):
            raise body
        return body

    async def get_json(self, url: str, **kw: Any) -> Any:
        return json.loads(await self.get_text(url, **kw))

    def form_session(self, **_: Any) -> _ReplayFormSession:
        return _ReplayFormSession(self)

    def stats(self) -> dict:
        return {"requests": dict(Counter(_host(u.split(" ")[1] if u.startswith("POST ") else u)
                                         for u in self.asked)), "errors": {}}
