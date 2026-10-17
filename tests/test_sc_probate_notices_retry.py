"""sc_probate_notices._fetch_paper: the "search_html" fallback's per-article page fetch gets
retry cushioning, not a silent, permanent drop of that one article's estate records.

Found 2026-10-17 (gap-sweep): the per-article fetch inside _fetch_paper()'s "search_html"
branch (`r = await c.get(u, timeout=60.0)`) was wrapped only in a bare
`except Exception: continue`, so a transient transport/timeout blip on any one of up to
MAX_DOCS article URLs was swallowed with zero retry of any kind -- unlike every other call
in this file, which is covered either by _json()'s RuntimeError-only local handling (a real
transport error there propagates up to SCProbateNotices.fetch()'s LayerHarvest, which retries
the whole paper) or, now, by this fix. Same root cause, same fix, as the Column legal-notice
API scrapers, spartan_weekly_legals.py, and arcgis_webmap.query_features() earlier the same
night: http_client.client()'s own docstring says every caller must wrap its own retries, and
this bare call never did.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import sc_probate_notices as m

PAPER = m.Paper("Cherokee", "www.gaffneyledger.com", "search_html")

SEARCH_PAGE = [{"url": "https://www.gaffneyledger.com/articles/estate-notice-1"}]

NOTICE_BODY = (
    "NOTICE TO CREDITORS OF ESTATES\n"
    "Estate: Dana Fowlerton Testcase\n"
    "Death: 06/19/2026\n"
    "Case# 2026ES1100303\n"
    "PR: Jordan Placeholder\n"
    "115 Sampleriver Dr.\n"
    "Moore, SC 29369\n"
)


class _FakeResp:
    def __init__(self, text="", status_code=200, json_payload=None):
        self.text = text
        self.status_code = status_code
        self._json_payload = json_payload

    def json(self):
        return self._json_payload


class _FlakyClient:
    """Serves the two search-JSON pages cleanly, then is flaky on the ONE article fetch."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.article_calls = 0

    async def get(self, url, timeout=None):
        if "/wp-json/wp/v2/search" in url:
            if "page=1" in url:
                return _FakeResp(json_payload=SEARCH_PAGE, status_code=200)
            return _FakeResp(json_payload=[], status_code=200)
        # The per-article fetch under test.
        self.article_calls += 1
        if self.article_calls <= self.fail_times:
            raise self.exc
        return _FakeResp(text=NOTICE_BODY, status_code=200)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """The loop also does a real 0.4s `asyncio.sleep` between articles; skip it in tests."""
    async def _noop(*a, **kw):
        return None
    monkeypatch.setattr(m.asyncio, "sleep", _noop)


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    c = _FlakyClient(fail_times=2)
    rows = asyncio.run(m._fetch_paper(c, PAPER))
    assert c.article_calls == 3
    assert len(rows) == 1
    assert rows[0].case_number == "2026ES1100303"


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs_and_the_article_is_dropped():
    c = _FlakyClient(fail_times=99)
    rows = asyncio.run(m._fetch_paper(c, PAPER))
    assert c.article_calls == 3           # stop_after_attempt(3), then gives up
    assert rows == []                     # the outer try/except still drops just this article


def test_a_read_timeout_is_also_retried():
    c = _FlakyClient(fail_times=1, exc=httpx.ReadTimeout("slow"))
    rows = asyncio.run(m._fetch_paper(c, PAPER))
    assert c.article_calls == 2
    assert len(rows) == 1


def test_a_real_non_200_status_is_not_retried():
    class _BadStatusClient:
        def __init__(self):
            self.article_calls = 0

        async def get(self, url, timeout=None):
            if "/wp-json/wp/v2/search" in url:
                if "page=1" in url:
                    return _FakeResp(json_payload=SEARCH_PAGE, status_code=200)
                return _FakeResp(json_payload=[], status_code=200)
            self.article_calls += 1
            return _FakeResp(text="", status_code=404)

    c = _BadStatusClient()
    rows = asyncio.run(m._fetch_paper(c, PAPER))
    assert c.article_calls == 1           # a real bad status is not a transport/timeout error
    assert rows == []                     # 404 -> never appended to docs, no notice parsed
