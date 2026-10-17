"""counties_nc.mcdowell_probate.McDowellProbate.fetch: a transient transport error on the
single ArcGIS query call gets retried, not treated as "the whole scrape failed."

Found 2026-10-17 (gap-sweep): the only network call in this file -- a paginated ArcGIS
FeatureServer query made via the shared ``http_client.client()`` helper -- was wrapped in a
bare ``try/except Exception: break`` with zero retry. ``http_client.client()``'s own
contract is that callers wrap their own retries (see its docstring / ``retries=0`` on its
transport); this one never did. Because the page size (2000) comfortably exceeds the real
dataset (~414 parcels), the first call is almost always the only call -- a true single
point of failure -- and this source is in ``main.DATELESS_OK_SOURCES`` (no fallback date
window), so a single transient blip would silently zero the whole scrape forever, reported
as a healthy empty result. Same bug shape already fixed tonight in: a Column legal-notice
API scraper, spartan_weekly_legals.py, and arcgis_webmap.query_features().

This test is offline (no network): it patches ``M.client`` (the module-level import of
``http_client.client``) with a fake async-context-manager yielding a fake http object,
exactly like the existing ``test_mcdowell_probate_legal_description.py`` does.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import mcdowell_probate as M


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FlakyHttp:
    """Raises on the first N-1 calls, then serves a real (empty, terminal) page."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def get(self, url, params=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp({"features": []})


class _BadStatusHttp:
    """A real non-200 status, never a transport/timeout error -- must not be retried."""

    def __init__(self):
        self.calls = 0

    async def get(self, url, params=None):
        self.calls += 1
        return _FakeResp({}, status_code=503)


def _patch_client(monkeypatch, fake):
    @asynccontextmanager
    async def cm(**kw):
        yield fake
    monkeypatch.setattr(M, "client", cm)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(M, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    http = _FlakyHttp(fail_times=2)
    _patch_client(monkeypatch, http)
    rows = asyncio.run(M.McDowellProbate().fetch())
    assert http.calls == 3
    assert rows == []


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs(monkeypatch):
    http = _FlakyHttp(fail_times=99)
    _patch_client(monkeypatch, http)
    # The outer try/except Exception: break swallows the re-raised timeout after the
    # retry budget is exhausted (unchanged existing behavior) -- it must NOT hang, and
    # must NOT have retried past stop_after_attempt(3).
    rows = asyncio.run(M.McDowellProbate().fetch())
    assert http.calls == 3   # stop_after_attempt(3), then gives up
    assert rows == []


def test_a_read_timeout_is_also_retried(monkeypatch):
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    _patch_client(monkeypatch, http)
    rows = asyncio.run(M.McDowellProbate().fetch())
    assert http.calls == 2
    assert rows == []


def test_a_real_http_error_status_is_not_retried(monkeypatch):
    http = _BadStatusHttp()
    _patch_client(monkeypatch, http)
    rows = asyncio.run(M.McDowellProbate().fetch())
    assert http.calls == 1   # a real bad status is not a transport/timeout error
    assert rows == []
