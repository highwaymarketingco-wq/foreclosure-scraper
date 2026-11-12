"""asheville_helene: both ArcGIS network calls get retry cushioning on a transient
transport error or timeout, instead of permanently zeroing the run.

Found 2026-10-17 (gap-sweep continuation): fetch()'s line-99 FeatureServer/0/query
call is the single ArcGIS query that returns every Unsafe/Restricted Helene-damage
feature (~650 structures) for the whole scrape. It went through http_client.client(),
which deliberately does not retry internally (callers must wrap their own
AsyncRetrying -- see http_client.py's own comment), and the call was wrapped only in
a bare ``try/except Exception: return []`` -- zero retry. A single transient
httpx.TransportError/TimeoutException permanently zeroed the whole run's output, and
this source is registered in main.DATELESS_OK_SOURCES (no fallback date window to
self-heal on later). Same root cause already fixed tonight for the Column
legal-notice API scrapers, spartan_weekly_legals.py, and arcgis_webmap.query_features().

_fetch_attachments()'s per-chunk queryAttachments call (line 59) had the identical
unprotected shape, just lower blast radius (a failed chunk only drops photos for
~150 features, never the whole scrape) -- wrapped the same way for consistency.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import asheville_helene as mod

FEATURE = {
    "attributes": {
        "objectid": 21, "incident_name": "Helene", "inspect_date": 1729257600000,
        "building_type": "Single Family", "building_primary_occupancy": "Residential",
        "building_damage": "Moderate", "previous_posting": "Unsafe",
        "current_posting": "Restricted", "building_number_res_units": 1,
    },
    "geometry": {"y": 35.5951, "x": -82.5515},
}


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# --------------------------------------------------------------------------- #
# fetch() -- the line-99 query call (PRIMARY: single point of failure for the
# whole scrape).
# --------------------------------------------------------------------------- #

class _FlakyMainQuery:
    """Fails the main FeatureServer query N times, then serves real features.
    A queryAttachments call (if the retried query ever returns features) always
    succeeds immediately so it can't interfere with the main-query call count."""

    def __init__(self, fail_times: int, exc=None, feats=None, status: int = 200):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.query_calls = 0
        self.attach_calls = 0
        self.feats = feats if feats is not None else []
        self.status = status

    async def get(self, url, params=None, timeout=None):
        if url == mod.QUERY_URL:
            self.query_calls += 1
            if self.query_calls <= self.fail_times:
                raise self.exc
            return _FakeResp({"features": self.feats}, status_code=self.status)
        if url == mod._ATTACH_URL:
            self.attach_calls += 1
            return _FakeResp({"attachmentGroups": []})
        raise AssertionError(f"unexpected url {url}")


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _run_fetch(http, monkeypatch):
    s = mod.AshevilleHeleneDamage()
    monkeypatch.delenv("FORECLOSURE_HELENE", raising=False)
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    return asyncio.run(s.fetch())


def test_a_transient_connect_timeout_on_the_main_query_is_retried_and_succeeds(monkeypatch):
    http = _FlakyMainQuery(fail_times=2, feats=[FEATURE])
    rows = _run_fetch(http, monkeypatch)
    assert http.query_calls == 3
    assert len(rows) == 1
    assert rows[0].raw["helene"]["current_posting"] == "Restricted"


def test_a_connect_timeout_that_never_clears_still_stops_not_hangs(monkeypatch):
    """stop_after_attempt(3) gives up; the outer bare except still turns that into
    the pre-existing 'return []' behavior -- it must not hang or retry forever."""
    http = _FlakyMainQuery(fail_times=99)
    rows = _run_fetch(http, monkeypatch)
    assert http.query_calls == 3
    assert rows == []


def test_a_read_timeout_on_the_main_query_is_also_retried(monkeypatch):
    http = _FlakyMainQuery(fail_times=1, exc=httpx.ReadTimeout("slow"), feats=[FEATURE])
    rows = _run_fetch(http, monkeypatch)
    assert http.query_calls == 2
    assert len(rows) == 1


def test_a_real_http_error_status_on_the_main_query_is_not_retried(monkeypatch):
    http = _FlakyMainQuery(fail_times=0, status=503)
    rows = _run_fetch(http, monkeypatch)
    assert http.query_calls == 1   # a real bad status is not a transport/timeout error
    assert rows == []


# --------------------------------------------------------------------------- #
# _fetch_attachments() -- the line-59 per-chunk queryAttachments call
# (SECONDARY: per-chunk photo loss only, wrapped for consistency).
# --------------------------------------------------------------------------- #

class _FlakyAttachments:
    def __init__(self, fail_times: int, exc=None, payload=None, status: int = 200):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0
        self.payload = payload if payload is not None else {"attachmentGroups": []}
        self.status = status

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self.payload, status_code=self.status)


def test_attachments_transient_timeout_is_retried_and_then_succeeds(monkeypatch):
    http = _FlakyAttachments(fail_times=2, payload={
        "attachmentGroups": [{"parentObjectId": 21, "attachmentInfos": [
            {"id": 12, "contentType": "image/jpeg"}]}]})
    out = asyncio.run(mod._fetch_attachments(http, [21]))
    assert http.calls == 3
    assert out[21] == [f"{mod._LAYER_BASE}/21/attachments/12"]


def test_attachments_timeout_that_never_clears_yields_no_photos_not_a_hang(monkeypatch):
    """Matches the existing 'never raises' contract: an exhausted retry budget on one
    chunk just means no photos for those ids, not a crash and not an infinite retry."""
    http = _FlakyAttachments(fail_times=99)
    out = asyncio.run(mod._fetch_attachments(http, [21]))
    assert http.calls == 3   # stop_after_attempt(3), then the chunk is skipped
    assert out == {}


def test_attachments_real_http_error_status_is_not_retried(monkeypatch):
    http = _FlakyAttachments(fail_times=0, status=500)
    out = asyncio.run(mod._fetch_attachments(http, [21]))
    assert http.calls == 1
    assert out == {}
