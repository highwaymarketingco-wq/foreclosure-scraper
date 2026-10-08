"""http_client.get_text retries only what can clear: a transport error, a timeout or a 5xx.
A 4xx (403, 404, 429) is asked once (audit 2026-10-09). No network: the client is faked."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
import tenacity

from foreclosure_scraper import http_client as H

URL = "https://example.invalid/page"


class _Client:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def get(self, url, headers=None):
        self.calls += 1
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return httpx.Response(item, text=f"body {item}", request=httpx.Request("GET", url))


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def install(script):
        cli = _Client(script)
        holder["c"] = cli

        @asynccontextmanager
        async def client(**kw):
            yield cli

        monkeypatch.setattr(H, "client", client)
        monkeypatch.setattr(H, "wait_exponential_jitter", lambda **kw: tenacity.wait_none())

        async def no_curl(*a, **kw):
            return ""
        monkeypatch.setattr(H, "_curl_fallback_text", no_curl)
        return cli
    return install


@pytest.mark.parametrize("code", [403, 404, 429])
def test_a_4xx_is_asked_once(fake, code):
    cli = fake([code])
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(H.get_text(URL))
    assert cli.calls == 1


@pytest.mark.parametrize("code", [500, 502, 503, 504])
def test_a_5xx_is_retried_three_times(fake, code):
    cli = fake([code])
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(H.get_text(URL))
    assert cli.calls == 3


def test_a_5xx_then_success_returns_the_page(fake):
    cli = fake([503, 200])
    assert asyncio.run(H.get_text(URL)) == "body 200"
    assert cli.calls == 2


def test_a_transport_error_is_still_retried(fake):
    req = httpx.Request("GET", URL)
    cli = fake([httpx.ConnectError("refused", request=req), httpx.ReadTimeout("slow", request=req), 200])
    assert asyncio.run(H.get_text(URL)) == "body 200"
    assert cli.calls == 3


def test_a_403_still_escalates_to_impersonation_when_allowed(fake, monkeypatch):
    cli = fake([403])
    seen = {}

    async def imp(url, **kw):
        seen["url"] = url
        return "impersonated"
    monkeypatch.setattr(H, "get_text_impersonate", imp)
    monkeypatch.setattr(H, "_impersonate_hosts", set())
    assert asyncio.run(H.get_text(URL, impersonate=True)) == "impersonated"
    assert cli.calls == 1 and seen["url"] == URL


def test_predicate():
    req = httpx.Request("GET", URL)
    err = lambda c: httpx.HTTPStatusError("x", request=req, response=httpx.Response(c, request=req))
    assert not H._retryable_get_error(err(429))
    assert not H._retryable_get_error(err(403))
    assert H._retryable_get_error(err(503))
    assert H._retryable_get_error(httpx.ConnectTimeout("t", request=req))
    assert not H._retryable_get_error(ValueError("parse"))
