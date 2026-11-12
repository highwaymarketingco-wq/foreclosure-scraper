"""spartan_weekly_legals: a transient transport error on a page fetch gets retried, not treated
as "end of notices."

2026-10-16: the live VM run's own log showed page 1's fetch fail with a bare exception, the loop
`break`ing immediately, and 0 leads landing where ~111/run is normal -- reported as a healthy
ZERO_RESULT (expected_min_count=0), not a visible failure. Same root cause, same fix, as the
Column legal-notice API scrapers fixed earlier the same night: client().get() had zero retry
cushioning, and http_client.client()'s own docstring says every caller is expected to wrap one.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import spartan_weekly_legals as M

PAGE = (
    '<div class="article col"><h6>Master In Equity</h6>'
    '<h4><a href="/legal-notices/12-testa-placeholder-rd">12 Testa Placeholder Rd</a></h4>'
    '<p> Case #:2026CP4200001<br> October 1, 2026 </p></div>'
)


def _fake_client(get_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        yield stub
    return _cm


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(M, "wait_exponential_jitter", lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_on_page_1_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        if "/legal-notices/?page=1" in url:
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ConnectTimeout("boom")
            return MagicMock(status_code=200, text=PAGE)
        return MagicMock(status_code=404, text="")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.SpartanWeeklyLegals().safe_run())
    assert calls["n"] == 3
    assert len(rows) == 1


def test_a_connect_timeout_that_never_clears_still_ends_cleanly_not_crashes(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.SpartanWeeklyLegals().safe_run())
    assert calls["n"] == 3                      # stop_after_attempt(3), then gives up gracefully
    assert rows == []


def test_a_real_404_on_page_1_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        return MagicMock(status_code=404, text="")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.SpartanWeeklyLegals().safe_run())
    assert calls["n"] == 1                      # a real bad status is not a transport/timeout error
    assert rows == []
