"""Iredell County NC delinquent-tax scraper: match_points(), the shared spatial-join helper
IredellDelinquentTax.fetch() calls (scrapers/counties_generic/_layer_kit.py), retries a
transient transport error on its batch POST instead of treating it as "the whole scrape
failed."

Investigated 2026-11-07: IredellDelinquentTax.fetch() has two network dependencies, both
reached through shared helpers rather than any bare call in iredell_delinquent_tax.py itself.
Call site 1 (arcgis_webmap.query_features, for the county's own outline layer) already wraps
its GET/POST in AsyncRetrying. Call site 2 (_layer_kit.match_points, joining each outline's
interior point to the NC OneMap statewide parcel layer, `where="cntyname='Iredell'"`) did not:
a transient blip on ANY ONE of its ~24 sequential batch POSTs (2,391 outline points /
batch=100) discarded the whole `out` accumulator and zeroed the entire run's result -- not
just that batch's ~100 points. Because this source is dateless (registered in
main.DATELESS_OK_SOURCES, no fallback date window), a zeroed run could not self-heal later; it
would just silently report an empty/healthy result until someone noticed by hand. match_points
is a shared helper (also used by Charleston's EnerGov point-matching), so wrapping its one POST
in the same proven AsyncRetrying pattern as arcgis_webmap.query_features() covers every caller,
not just Iredell.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.parcel_cache import NC_ONEMAP_URL
from foreclosure_scraper.scrapers.counties_generic import _layer_kit as lk
from foreclosure_scraper.scrapers.counties_nc import iredell_delinquent_tax as IR

LAYER = NC_ONEMAP_URL.rsplit("/query", 1)[0]
FIELDS = IR.ONEMAP_FIELDS
POINTS = [(-80.887, 35.783)]   # one interior point, Statesville NC area
WHERE = "cntyname='Iredell'"   # the actual WHERE iredell_delinquent_tax.py passes


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

    async def post(self, url, data=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp({"features": []})


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(lk, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2)
    out = asyncio.run(lk.match_points(http, LAYER, POINTS, FIELDS, where=WHERE, delay_s=0))
    assert http.calls == 3
    assert out == [None]


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    http = _FlakyHttp(fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(lk.match_points(http, LAYER, POINTS, FIELDS, where=WHERE, delay_s=0))
    assert http.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite hang


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    out = asyncio.run(lk.match_points(http, LAYER, POINTS, FIELDS, where=WHERE, delay_s=0))
    assert http.calls == 2
    assert out == [None]


def test_a_real_http_error_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def post(self, url, data=None, timeout=None):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    http = _BadStatusHttp()
    with pytest.raises(RuntimeError):
        asyncio.run(lk.match_points(http, LAYER, POINTS, FIELDS, where=WHERE, delay_s=0))
    assert http.calls == 1   # a real bad status is not a transport/timeout error


def test_a_200_with_an_error_body_is_not_retried():
    class _ErrorBodyHttp:
        def __init__(self):
            self.calls = 0

        async def post(self, url, data=None, timeout=None):
            self.calls += 1
            return _FakeResp({"error": {"code": 400, "message": "layer unavailable"}})

    http = _ErrorBodyHttp()
    with pytest.raises(RuntimeError):
        asyncio.run(lk.match_points(http, LAYER, POINTS, FIELDS, where=WHERE, delay_s=0))
    assert http.calls == 1   # the classic HTTP-200-plus-error-body silent-death shape, unretried
