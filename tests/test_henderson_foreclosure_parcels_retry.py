"""henderson_foreclosure_parcels.fetch_source: a transient transport error on the
agw.walk_layers() call gets retried, not treated as "the whole scrape failed."

fetch_source() has exactly two network-reaching calls through the shared
arcgis_webmap (agw) module: agw.walk_layers() (app -> web map -> layer list) and
agw.query_attributes()/query_features() (the parcel rows). query_features()'s own
bare http.get()/.post() already carries the proven AsyncRetrying cushion (see
test_arcgis_webmap_query_features_retry.py). walk_layers() had none of its own, and
this file cannot touch arcgis_webmap.py, so the retry is wrapped locally around the
agw.walk_layers(...) call in fetch_source() -- modeled on that same reference test's
shape and fixture style, but at the agw.walk_layers() call boundary (the dependency
this file actually calls) rather than at the raw httpx.AsyncClient boundary, matching
this file's own existing convention of monkeypatching ``mod.agw.walk_layers`` (see
test_henderson_foreclosure_parcels.py::test_scraper_reports_error_not_zero_when_the_chain_breaks).

NOTE on scope: agw.walk_layers() resolves through agw.fetch_item_data(), whose own
portal-fallback loop re-raises every per-portal failure -- a transient transport/
timeout error included -- as a plain agw.ArcGisError once all configured portals are
exhausted, discarding the original exception's type. That means the "a real transient
blip hits every configured portal" shape currently surfaces to this wrapper as
ArcGisError, not as httpx.TransportError/TimeoutException, and is NOT retried by this
fix (test_a_real_arcgis_error_from_an_exhausted_portal_fallback_is_not_retried below
documents exactly that boundary). This wrapper does retry a transport/timeout error
that reaches fetch_source() directly through agw.walk_layers(), and will start
covering the exhausted-portal shape too the moment agw.fetch_item_data() is fixed to
preserve the real exception type on exhaustion -- that companion fix belongs in
arcgis_webmap.py, out of scope for this file.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper import arcgis_webmap as agw
from foreclosure_scraper.scrapers.counties_nc import henderson_foreclosure_parcels as mod

SRC = mod._SOURCES[0]


class _FlakyWalkLayers:
    """Raises on the first N-1 calls, then returns a real (empty, terminal) layer list.

    An empty layer list is a valid, successful agw.walk_layers() return: fetch_source()
    then finds no matching layer, logs a warning, and returns [] -- no further I/O
    needed, which keeps this test isolated to the retry wrapper alone.
    """

    def __init__(self, fail_times: int, exc: Exception | None = None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def __call__(self, http, item_id, portals=(), **kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return []


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyWalkLayers(fail_times=2)
    monkeypatch.setattr(mod.agw, "walk_layers", fake)
    rows = asyncio.run(mod.fetch_source(None, SRC))
    assert fake.calls == 3
    assert rows == []


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs(monkeypatch):
    fake = _FlakyWalkLayers(fail_times=99)
    monkeypatch.setattr(mod.agw, "walk_layers", fake)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(mod.fetch_source(None, SRC))
    assert fake.calls == 3   # stop_after_attempt(3), then gives up


def test_a_read_timeout_is_also_retried(monkeypatch):
    fake = _FlakyWalkLayers(fail_times=1, exc=httpx.ReadTimeout("slow"))
    monkeypatch.setattr(mod.agw, "walk_layers", fake)
    rows = asyncio.run(mod.fetch_source(None, SRC))
    assert fake.calls == 2
    assert rows == []


def test_a_bare_asyncio_timeouterror_is_also_retried(monkeypatch):
    fake = _FlakyWalkLayers(fail_times=1, exc=TimeoutError("timed out"))
    monkeypatch.setattr(mod.agw, "walk_layers", fake)
    rows = asyncio.run(mod.fetch_source(None, SRC))
    assert fake.calls == 2
    assert rows == []


def test_a_real_arcgis_error_is_not_retried(monkeypatch):
    """A real, non-transport failure -- including the shape agw.walk_layers() itself
    raises once agw.fetch_item_data() exhausts every configured portal -- must fail
    immediately on attempt 1, exactly like a real bad HTTP status is never retried in
    test_arcgis_webmap_query_features_retry.py::test_a_real_http_error_status_is_not_retried.
    """
    calls = {"n": 0}

    async def boom(http, item_id, portals=(), **kw):
        calls["n"] += 1
        raise agw.ArcGisError(f"item {item_id} unreadable: HTTP 403")

    monkeypatch.setattr(mod.agw, "walk_layers", boom)
    with pytest.raises(agw.ArcGisError):
        asyncio.run(mod.fetch_source(None, SRC))
    assert calls["n"] == 1   # not a transport/timeout error -- never retried
