"""lincoln_vacant.LincolnVacant.fetch: a transient transport/timeout error on the ArcGIS
page fetch gets retried, not treated as "the whole scrape failed."

Found 2026-11-07 (gap-sweep): the pagination loop's only network call --
``r = await c.get(QUERY_URL, params=params)`` -- runs on a bare, inline
``httpx.AsyncClient(verify=False, timeout=60.0)`` (verify=False because the host serves
an incomplete TLS cert chain, not an expired cert -- see lincoln_vacant.py's docstring --
so this scraper never goes through the shared, already-retrying ``http_client.client()``
helper) with zero retry cushioning,
guarded only by a bare ``except Exception: break``. Because the FIRST page
(offset=0) runs on every single invocation and every page appends to one shared
``out`` list, a transient blip on that first call silently zeroed (or, on a later
page, silently truncated) this whole dateless source's output for the run --
reported as a healthy result, since this scraper is registered in
main.DATELESS_OK_SOURCES (no fallback date window to self-heal from). Same root
cause, same fix, already shipped for gaston_vacant.py (the closest sibling: same
county-GIS pagination shape), the Column legal-notice API scrapers,
spartan_weekly_legals.py, and the shared arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import lincoln_vacant as m

ONE_FEATURE_PAGE = {"features": [{"attributes": {
    "PARCELID": "50396", "PIN": "2646977606",
    "PHYSICALADDR": "OLD NC 18 RD", "NAME1": "TEST OWNER",
}}]}
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
    """Stands in for the ``async with httpx.AsyncClient(...) as c:`` block."""

    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _run_fetch(http):
    # Same monkeypatch mechanism as the existing test_lincoln_vacant.py: this
    # module builds its ArcGIS client inline (``httpx.AsyncClient(verify=False,
    # ...)``) rather than through the shared http_client.client() helper, so
    # there is no module-level ``client`` name to swap -- only ``httpx.AsyncClient``
    # itself.
    original = m.httpx.AsyncClient
    m.httpx.AsyncClient = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(m.LincolnVacant().fetch())
    finally:
        m.httpx.AsyncClient = original


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(m, "wait_exponential_jitter",
                         lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2, final_payload=ONE_FEATURE_PAGE)
    out = _run_fetch(http)
    assert http.calls == 3
    assert len(out) == 1
    # PIN wins over PARCELID for parcel_id (owner decision 2026-10-07) -- proves
    # the retried page was parsed through the real, unchanged request logic.
    assert out[0].parcel_id == "2646977606"


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"), final_payload=ONE_FEATURE_PAGE)
    out = _run_fetch(http)
    assert http.calls == 2
    assert len(out) == 1


def test_a_plain_timeout_error_is_also_retried():
    # TimeoutError (the builtin, distinct from httpx.TimeoutException) is the
    # third member of the retry predicate's exception tuple -- cover it too.
    http = _FlakyHttp(fail_times=1, exc=TimeoutError("asyncio budget exceeded"),
                       final_payload=ONE_FEATURE_PAGE)
    out = _run_fetch(http)
    assert http.calls == 2
    assert len(out) == 1


def test_a_connect_timeout_that_never_clears_still_ends_cleanly_not_hangs():
    http = _FlakyHttp(fail_times=99)  # always raises
    out = _run_fetch(http)
    assert http.calls == 3   # stop_after_attempt(3), then AsyncRetrying re-raises --
                              # the pre-existing outer except/break (left untouched)
                              # ends the loop cleanly instead of hanging or crashing.
    assert out == []


def test_a_real_bad_http_status_is_not_retried():
    http = _FlakyHttp(fail_times=0, final_status=503, final_payload={})
    out = _run_fetch(http)
    assert http.calls == 1   # a real bad status is not a transport/timeout error
    assert out == []
