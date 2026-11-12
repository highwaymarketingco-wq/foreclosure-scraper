"""Buncombe County NC tax foreclosures (counties_nc/buncombe_tax.py): BuncombeTax.fetch
retries a transient transport error on the Trumba JSON calendar GET instead of silently
zeroing the whole scrape.

2026-10-17: fetch() calls http_client.client() directly (not the retry-wrapped
get_text/get_bytes helpers) and wrapped its single `c.get(JSON_URL, params=params)` in a
bare `try: ... except Exception: return []` -- a swallow, not a retry. http_client.client()
sets the transport's own retries=0 BY DESIGN (its own docstring: "callers already wrap their
own AsyncRetrying"), so a single transient connection reset or timeout fell straight through
to that bare except and returned [] on the first try. "counties_nc.buncombe_tax" is listed in
main.DATELESS_OK_SOURCES (confirmed via grep, matching the file's own docstring claim), so a
zeroed run from a transient blip has no fallback date window and silently reports an
empty/healthy result until someone notices by hand -- the same bug shape already fixed
elsewhere tonight (Column legal-notice API, spartan_weekly_legals.py, arcgis_webmap's
query_features()).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import buncombe_tax as m

GEO_EVENT = {
    "eventID": 1, "title": "LARRY A WOOTEN",
    "description": "** PROPERTY HAS BEEN REDEEMED **",
    "location": ('<a href="http://maps.google.com/?q=35.785141,-82.432815(LARRY+A+WOOTEN)" '
                 'target="_blank" rel="noopener">368 N FORK RD BARNARDSVILLE</a>'),
    "startDateTime": "2024-01-24T11:15:00",
    "customFields": [
        {"label": "Opening/Current Bid", "value": "$6,909.03"},
        {"label": "Redeemed", "value": "No"},
        {"label": "Case Number", "value": "23 CVD 03805"},
    ],
    "permaLinkUrl": "https://taxforeclosures.buncombenc.gov/x1",
}


class _FakeResp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


class _FlakyHttp:
    """Raises on the first N-1 calls, then serves a real (terminal) JSON page."""

    def __init__(self, fail_times: int, exc=None, body: str = "[]"):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0
        self._body = body

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self._body)


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _run_fetch_with(http) -> list:
    s = m.BuncombeTax()
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(s.fetch())
    finally:
        m.client = original


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """The real backoff is 1-8s per attempt; make the retry tests instant."""
    monkeypatch.setattr(m, "wait_exponential_jitter",
                         lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    import json
    http = _FlakyHttp(fail_times=2, body=json.dumps([GEO_EVENT]))
    rows = _run_fetch_with(http)
    assert http.calls == 3
    assert len(rows) == 1
    assert rows[0].defendant == "LARRY A WOOTEN"


def test_a_read_timeout_is_also_retried():
    import json
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"), body=json.dumps([]))
    rows = _run_fetch_with(http)
    assert http.calls == 2
    assert rows == []


def test_a_connect_timeout_that_never_clears_still_returns_empty_not_hang():
    """stop_after_attempt(3) bounds it -- a persistently-flaky host degrades to the
    existing [] contract (fetch()'s own bare except Exception) after exactly 3 tries,
    it never retries forever and never raises out past that existing contract."""
    http = _FlakyHttp(fail_times=99)
    rows = _run_fetch_with(http)
    assert http.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite hang
    assert rows == []


def test_a_real_bad_http_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _FakeResp("", status_code=503)

    http = _BadStatusHttp()
    rows = _run_fetch_with(http)
    assert http.calls == 1   # a real bad status is not a transport/timeout error
    assert rows == []
