"""rutherford_wildfire_tax._post_page: a transient transport error on the Wildfire
Records POST gets retried, not left to escape the whole sweep.

Found 2026-10-17 (gap-sweep): _post_page()'s single `c.post(...)` call had zero retry
cushioning -- the exact same gap already fixed tonight for the Column legal-notice API
scraper, spartan_weekly_legals.py, arcgis_webmap.query_features() and
rutherford_tax._pin_map(). _post_page's own manual retry loop only retries AFTER a
response is received (429/503 honoring Retry-After); nothing wrapped the POST call
itself, so an httpx.TransportError/TimeoutException escaped _post_page uncaught, then
escaped _sweep_year (whose try only catches PermissionError) and fetch()'s per-year loop
(whose except only catches WildfireWall and (WildfireNotJson, RuntimeError, OSError) --
none of which httpx's transport/timeout exceptions are). A single connection blip on any
one of the ~1,400 pages across all 10 tax years crashed the entire scrape for this run
instead of just that page, and because this slug is in main.DATELESS_OK_SOURCES (no
fallback date window), a zeroed run cannot self-heal later.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import rutherford_wildfire_tax as rwt

URL = "https://d1ebsyxxbc7tep.cloudfront.net/data/5b88e44b-0038-4361-8c53-7ce1343ad3ad/Wildfire/Records"
BODY = {"value": "", "skip": 0, "facets": {"Status": {"Unpaid": True}}, "direct": False}


class _FakeResp:
    def __init__(self, payload=None, status_code=200, headers=None, text=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers if headers is not None else {}
        self._text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no payload")
        return self._payload

    @property
    def text(self):
        if self._text is not None:
            return self._text
        return json.dumps(self._payload) if self._payload is not None else ""


def _ok_page():
    return _FakeResp(
        {"SearchToken": "tok", "TotalRecords": 0, "Records": []},
        status_code=200,
        headers={"content-type": "application/json"},
    )


class _FlakyClient:
    """Raises on the first N-1 ``post`` calls, then serves a real (empty, terminal) page."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def post(self, url, content=None, headers=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _ok_page()


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(rwt, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    c = _FlakyClient(fail_times=2)
    payload = asyncio.run(rwt._post_page(c, URL, BODY, None))
    assert c.calls == 3
    assert payload == {"SearchToken": "tok", "TotalRecords": 0, "Records": []}


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    c = _FlakyClient(fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(rwt._post_page(c, URL, BODY, None))
    assert c.calls == 3   # stop_after_attempt(3), then gives up -- never hangs


def test_a_read_timeout_is_also_retried():
    c = _FlakyClient(fail_times=1, exc=httpx.ReadTimeout("slow"))
    payload = asyncio.run(rwt._post_page(c, URL, BODY, None))
    assert c.calls == 2
    assert payload == {"SearchToken": "tok", "TotalRecords": 0, "Records": []}


def test_a_403_wall_is_not_retried():
    """A real HTTP 403 is the owner's own definition of a wall (WildfireWall) -- it
    must fail on attempt 1, never be treated as a transient blip."""
    class _WalledClient:
        def __init__(self):
            self.calls = 0

        async def post(self, url, content=None, headers=None):
            self.calls += 1
            return _FakeResp(status_code=403, headers={}, text="")

    c = _WalledClient()
    with pytest.raises(rwt.WildfireWall):
        asyncio.run(rwt._post_page(c, URL, BODY, None))
    assert c.calls == 1   # a real bad status is not a transport/timeout error


def test_a_non_json_200_is_not_retried():
    """The Accept-header silent-success trap (a 200 HTML 'Data Only' page) is a real,
    terminal failure mode -- not a transport error -- so it must not be retried."""
    class _HtmlClient:
        def __init__(self):
            self.calls = 0

        async def post(self, url, content=None, headers=None):
            self.calls += 1
            return _FakeResp(status_code=200, headers={"content-type": "text/html"},
                              text="<html><title>Avalon :: Data Only</title></html>")

    c = _HtmlClient()
    with pytest.raises(rwt.WildfireNotJson):
        asyncio.run(rwt._post_page(c, URL, BODY, None))
    assert c.calls == 1
