"""gaston_vacant.GastonVacant.fetch: a transient transport/timeout error on the ArcGIS
page fetch gets retried, not treated as "the whole scrape failed."

Found 2026-10-17 (gap-sweep): the pagination loop's only network call --
``r = await c.get(QUERY_URL, params=params)`` -- went through the shared, throttled
``client()`` helper directly with zero retry cushioning, guarded only by a bare
``except Exception: break``. The helper's own docstring says callers must wrap their own
AsyncRetrying; this module never did. Because the FIRST page (offset=0) runs on every
single invocation and every page appends to one shared ``out`` list, a transient blip on
that first call silently zeroed this whole dateless source's output for the run --
reported as a healthy empty result, since this scraper is registered in
main.DATELESS_OK_SOURCES (no fallback date window to self-heal from). Same root cause,
same fix, already shipped tonight for the Column legal-notice API scrapers,
spartan_weekly_legals.py, and the shared arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import gaston_vacant as m

ONE_FEATURE_PAGE = {"features": [{"attributes": {"PIN": "TESTPIN1", "VacantImpro": "Vacant"}}]}
EMPTY_PAGE = {"features": []}


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FlakyHttp:
    """Raises on the first N calls, then serves a real (terminal, single-page) response."""

    def __init__(self, fail_times: int, exc=None, final_payload=None, final_status=200):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.final_payload = final_payload if final_payload is not None else EMPTY_PAGE
        self.final_status = final_status
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self.final_payload, self.final_status)


class _Ctx:
    """Stands in for the ``async with client(...) as c:`` block."""

    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _run_fetch(http):
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(m.GastonVacant().fetch())
    finally:
        m.client = original


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(m, "wait_exponential_jitter",
                         lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2, final_payload=ONE_FEATURE_PAGE)
    out = _run_fetch(http)
    assert http.calls == 3
    assert len(out) == 1
    assert out[0].parcel_id == "TESTPIN1"


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"), final_payload=ONE_FEATURE_PAGE)
    out = _run_fetch(http)
    assert http.calls == 2
    assert len(out) == 1


def test_a_connect_timeout_that_never_clears_still_ends_cleanly_not_hangs():
    http = _FlakyHttp(fail_times=99)  # always raises
    out = _run_fetch(http)
    assert http.calls == 3   # stop_after_attempt(3), then gives up -- the outer
                              # except/break ends the loop instead of hanging or crashing
    assert out == []


def test_a_real_bad_http_status_is_not_retried():
    http = _FlakyHttp(fail_times=0, final_status=503, final_payload={})
    out = _run_fetch(http)
    assert http.calls == 1   # a real bad status is not a transport/timeout error
    assert out == []


# --- 2026-11-10: HERMES triage follow-up flagged this source zero-row, "ArcGIS
# MapServer query failing". Live-reverified the same day: QUERY_URL/_WHERE/_OUT are
# all still correct (an unmodified fetch() returned 21,785 real rows live), but this
# host answers a bad/failed query with HTTP 200 and a JSON {"error": {...}} envelope
# -- live-confirmed with a deliberately bogus outFields/where -- not a non-200 status
# or a transport exception. The OLD code did `r.json().get("features", [])`
# unconditionally, so an error envelope silently read as "zero features = real end of
# pagination", with NO exception and NO retry -- on offset=0 that zeroes the entire
# source. These tests cover the widened retry that now catches it. ---

ERROR_ENVELOPE = {"error": {"code": 400, "message": "Failed to execute query.", "details": []}}


class _JsonRaisingResp:
    """A response whose .json() raises -- simulates a non-JSON/empty body (the
    literal 2026-11-09 field-audit observation: 'ArcGIS returned empty body today')."""

    def __init__(self, status_code=200):
        self.status_code = status_code

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


class _ArcGisErrorEnvelopeHttp:
    """Always answers HTTP 200; the BODY is an ArcGIS {"error": ...} envelope for the
    first N calls, then a real (terminal, single-page) feature payload."""

    def __init__(self, fail_times: int, final_payload=None):
        self.fail_times = fail_times
        self.final_payload = final_payload if final_payload is not None else ONE_FEATURE_PAGE
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            return _FakeResp(ERROR_ENVELOPE, 200)
        return _FakeResp(self.final_payload, 200)


class _NonJsonBodyHttp:
    """Always answers HTTP 200; .json() raises for the first N calls (non-JSON/empty
    body), then a real payload."""

    def __init__(self, fail_times: int, final_payload=None):
        self.fail_times = fail_times
        self.final_payload = final_payload if final_payload is not None else ONE_FEATURE_PAGE
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            return _JsonRaisingResp()
        return _FakeResp(self.final_payload, 200)


def test_an_arcgis_error_envelope_is_retried_and_then_succeeds():
    http = _ArcGisErrorEnvelopeHttp(fail_times=2)
    out = _run_fetch(http)
    assert http.calls == 3
    assert len(out) == 1
    assert out[0].parcel_id == "TESTPIN1"


def test_an_arcgis_error_envelope_that_never_clears_still_ends_cleanly_not_hangs():
    http = _ArcGisErrorEnvelopeHttp(fail_times=99)  # always answers with the envelope
    out = _run_fetch(http)
    assert http.calls == 3   # stop_after_attempt(3), same backstop as a transport error
    assert out == []


def test_a_non_json_empty_body_is_also_retried_and_then_succeeds():
    http = _NonJsonBodyHttp(fail_times=1)
    out = _run_fetch(http)
    assert http.calls == 2
    assert len(out) == 1


def test_a_legitimate_empty_last_page_is_not_confused_with_an_error_and_not_retried():
    # A genuinely-finished pagination (real end of data) has no "error" key, just an
    # empty features list -- must NOT be treated as an ArcGIS error / retried.
    http = _FlakyHttp(fail_times=0, final_payload=EMPTY_PAGE)
    out = _run_fetch(http)
    assert http.calls == 1  # no retries triggered by a legitimate empty page
    assert out == []
