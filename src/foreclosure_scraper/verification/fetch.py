"""The `client` a verifier's verify(row, client) receives.

Fetcher       live: http_client.get_text (its per-host throttle, retries, curl fallback and
              optional Chrome-TLS impersonation) plus an extra per-host minimum spacing for a
              long background sweep (VERIFY_HOST_MIN_INTERVAL_S, default 1.5 s), request
              counts per host, and optional capture of every response body to a directory
              (the sweep's --capture-dir; that is how test fixtures are recorded).
ReplayFetcher tests: answers from a {url: body | Exception} map and records what was asked,
              so a verifier is tested against real captured responses with no network.

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
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


class Fetcher:
    def __init__(self, *, min_interval_s: Optional[float] = None, timeout: float = 25.0,
                 capture_dir: Optional[Path | str] = None) -> None:
        self.min_interval_s = float(os.environ.get("VERIFY_HOST_MIN_INTERVAL_S", "1.5")
                                    if min_interval_s is None else min_interval_s)
        self.timeout = timeout
        self.capture_dir = Path(capture_dir) if capture_dir else None
        self.requests: Counter = Counter()
        self.errors: Counter = Counter()
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _pace(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self.min_interval_s - (time.monotonic() - self._last.get(host, 0.0))
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

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

    def _capture(self, url: str, text: str) -> None:
        if not self.capture_dir:
            return
        try:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^A-Za-z0-9]+", "_", urlsplit(url).path).strip("_")[-80:]
            h = hashlib.sha256(url.encode()).hexdigest()[:8]
            (self.capture_dir / f"{_host(url)}__{slug}__{h}.html").write_text(text, encoding="utf-8")
            with open(self.capture_dir / "index.tsv", "a", encoding="utf-8") as fh:
                fh.write(f"{_host(url)}__{slug}__{h}.html\t{url}\n")
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

    def stats(self) -> dict:
        return {"requests": dict(Counter(_host(u) for u in self.asked)), "errors": {}}
