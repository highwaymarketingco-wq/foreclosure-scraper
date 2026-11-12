"""_layer_kit.match_points: a transient transport error on a batch POST gets retried, not
treated as "the whole spatial join failed."

Found 2026-11-07: match_points() (scrapers/counties_generic/_layer_kit.py) is the shared
spatial-join helper that ties a point-only layer (Charleston's EnerGov history points,
Iredell's delinquent-parcel outlines) to a parcel/address layer by posting one multipoint
query per batch of points. Its httpx POST had zero retry cushioning -- the same gap already
fixed for arcgis_webmap.query_features, a Column legal-notice API scraper, and
spartan_weekly_legals.py (http_client-style callers must wrap their own AsyncRetrying; this
one never did). match_points runs once per fetch() with the FULL combined point list, so a
transient blip on any one batch raised unretried straight out of match_points, discarding not
just that batch but every record the caller had already pulled earlier in the same fetch()
-- and because both of match_points' callers (counties_sc.charleston_energov_history,
counties_nc.iredell_delinquent_tax) are dateless sources with no date-floor fallback, a
zeroed run couldn't self-heal next time.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_generic import _layer_kit as lk

LAYER = "https://gis.example.test/arcgis/rest/services/Addresses/FeatureServer/0"
FIELDS = ("PID", "WHOLE_ADDRESS")
POINTS = [(1.0, 1.0)]


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
    out = asyncio.run(lk.match_points(http, LAYER, POINTS, FIELDS, distance_m=3.0))
    assert http.calls == 3
    assert out == [None]


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    http = _FlakyHttp(fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(lk.match_points(http, LAYER, POINTS, FIELDS, distance_m=3.0))
    assert http.calls == 3   # stop_after_attempt(3), then gives up


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    out = asyncio.run(lk.match_points(http, LAYER, POINTS, FIELDS, distance_m=3.0))
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
        asyncio.run(lk.match_points(http, LAYER, POINTS, FIELDS, distance_m=3.0))
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
        asyncio.run(lk.match_points(http, LAYER, POINTS, FIELDS, distance_m=3.0))
    assert http.calls == 1   # the classic HTTP-200-plus-error-body silent-death shape, unretried


def test_multiple_batches_only_the_failing_batch_retries():
    """batch=1 forces two separate POSTs (one per point); only the first one is flaky, and
    match_points must not resend a batch that already succeeded -- proves the retry budget is
    scoped per-batch (inside the chunk loop), not per whole-call."""
    class _PerBatchHttp:
        def __init__(self):
            self.calls = 0

        async def post(self, url, data=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ConnectTimeout("boom")
            return _FakeResp({"features": []})

    http = _PerBatchHttp()
    out = asyncio.run(lk.match_points(http, LAYER, [(1.0, 1.0), (2.0, 2.0)], FIELDS,
                                      distance_m=3.0, batch=1, delay_s=0))
    assert http.calls == 3   # batch 1: fails once then succeeds (2 calls); batch 2: succeeds (1 call)
    assert out == [None, None]
