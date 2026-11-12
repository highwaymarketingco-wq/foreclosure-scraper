"""reo.vrm_va_reo: both outbound network calls go through http_client.client(),
which deliberately sets ``httpx.AsyncHTTPTransport(retries=0)`` -- its own comment
says callers must wrap their own ``AsyncRetrying``. Neither call site did.

Found 2026-10-17 (gap-sweep): the primary SPOF is ``_fetch_state()``'s listing-search
page fetch -- the page-walk loop starts fresh (``out=[]``/``seen_ids=set()``) on every
call to ``_fetch_state`` and the surrounding ``try/except Exception`` just logs a
warning and ``break``s on ANY exception, including a transient
``httpx.TransportError``/``TimeoutException``. Because this runs ``for page in
range(1, 31)`` starting from page 1, a single transient blip on an early page
permanently zeroes that state's entire scrape for the run -- and because this source
has no fallback date window (``main.DATELESS_OK_SOURCES``), a zeroed run can't
self-heal later; it just silently reports an empty/healthy result. Same root cause,
same fix, already shipped tonight for the Column legal-notice API scraper,
spartan_weekly_legals.py, and arcgis_webmap.query_features().

The secondary call site is ``_enrich_from_detail()``'s per-listing detail-page fetch
-- lower severity (a failure there only skips one listing's enrichment, never the
card-level row), but genuinely the same unprotected pattern, so it gets the same
cushioning.

Modeled on tests/test_arcgis_webmap_query_features_retry.py.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.reo import vrm_va_reo as M

# A "page" response long enough to pass the `len(r.text) < 1000` floor but with no
# `div.card` elements, so the page-walk loop sees zero new listings and walks off
# the end cleanly on its own (not via an exception).
EMPTY_PAGE_HTML = "<html><body>" + ("z" * 1200) + "</body></html>"


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Same trick as the arcgis_webmap reference test: swap in a near-zero backoff
    so these tests don't actually sleep through tenacity's exponential-jitter wait."""
    monkeypatch.setattr(M, "wait_exponential_jitter",
                         lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _patch_client(monkeypatch, get_fn):
    """Stand in for http_client.client() the same way
    test_fetch_state_respects_the_detail_budget (test_vrm_va_reo_detail_page.py)
    already does -- an async context manager yielding a stub whose .get() we control."""
    @asynccontextmanager
    async def fake_client(*_a, **_kw):
        stub = MagicMock()
        stub.get = get_fn
        yield stub

    monkeypatch.setattr(M, "client", fake_client)


def _make_listing() -> "M.Listing":
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind
    return Listing(
        source="reo.vrm_va_reo",
        source_url="https://vrmproperties.com/Property-For-Sale/31766/508-redwood-pl",
        listing_type=ListingType.REO, property_kind=PropertyKind.SINGLE_FAMILY,
        state="NC", street_address="508 Redwood Pl Unit#2", city="Jacksonville",
        case_number="vrm-31766", opening_bid=199000.0,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={"vrm_id": "31766", "vrm_va_reo": {}},
    )


# --- _fetch_state: the primary SPOF call site -------------------------------

def test_fetch_state_retries_a_transient_transport_error_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, follow_redirects=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectTimeout("boom")
        return MagicMock(status_code=200, text=EMPTY_PAGE_HTML)

    _patch_client(monkeypatch, get)
    out = asyncio.run(M._fetch_state("NC", "reo.vrm_va_reo"))
    assert calls["n"] == 2   # 1 failed attempt + 1 retried success
    assert out == []         # the (empty) page was reached and walked off cleanly


def test_fetch_state_a_read_timeout_is_also_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, follow_redirects=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow")
        return MagicMock(status_code=200, text=EMPTY_PAGE_HTML)

    _patch_client(monkeypatch, get)
    out = asyncio.run(M._fetch_state("NC", "reo.vrm_va_reo"))
    assert calls["n"] == 2
    assert out == []


def test_fetch_state_gives_up_after_the_retry_budget_not_hang(monkeypatch):
    """A transient error that NEVER clears must still terminate (stop_after_attempt(3)),
    not retry forever -- and the outer try/except must still degrade this to a clean,
    bounded empty result rather than crashing the whole scraper run."""
    calls = {"n": 0}

    async def get(url, headers=None, follow_redirects=None):
        calls["n"] += 1
        raise httpx.ConnectTimeout("boom")  # never clears

    _patch_client(monkeypatch, get)
    out = asyncio.run(M._fetch_state("NC", "reo.vrm_va_reo"))
    assert calls["n"] == 3   # stop_after_attempt(3), then gives up
    assert out == []         # degrades gracefully instead of hanging or raising out


def test_fetch_state_does_not_retry_a_real_bad_status(monkeypatch):
    """A real non-transport HTTP error status is not a transport/timeout error --
    it must fail (here: just break the page-walk loop) on attempt 1, unretried."""
    calls = {"n": 0}

    async def get(url, headers=None, follow_redirects=None):
        calls["n"] += 1
        return MagicMock(status_code=500, text="z" * 1200)

    _patch_client(monkeypatch, get)
    out = asyncio.run(M._fetch_state("NC", "reo.vrm_va_reo"))
    assert calls["n"] == 1
    assert out == []


# --- _enrich_from_detail: the secondary, per-listing call site --------------

DETAIL_HTML_WITH_YEAR = (
    "<html><body>"
    '<div class="col-6 mb-2">Year Built</div><div class="col-6 mb-2">2023</div>'
    + ("y" * 1100) + "</body></html>"
)


def test_enrich_from_detail_retries_a_transient_error_then_succeeds():
    calls = {"n": 0}

    async def get(*_a, **_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow")
        return MagicMock(status_code=200, text=DETAIL_HTML_WITH_YEAR)

    c = MagicMock()
    c.get = get
    li = _make_listing()
    asyncio.run(M._enrich_from_detail(c, li))
    assert calls["n"] == 2
    assert li.year_built == 2023   # the retried fetch's fields actually landed


def test_enrich_from_detail_gives_up_after_retry_budget_not_hang():
    calls = {"n": 0}

    async def get(*_a, **_kw):
        calls["n"] += 1
        raise httpx.ConnectTimeout("boom")  # never clears

    c = MagicMock()
    c.get = get
    li = _make_listing()
    asyncio.run(M._enrich_from_detail(c, li))  # must not raise -- "never costs the row"
    assert calls["n"] == 3
    assert li.year_built is None   # untouched, not crashed


def test_enrich_from_detail_does_not_retry_a_real_bad_status():
    calls = {"n": 0}

    async def get(*_a, **_kw):
        calls["n"] += 1
        return MagicMock(status_code=404, text="z" * 1200)

    c = MagicMock()
    c.get = get
    li = _make_listing()
    asyncio.run(M._enrich_from_detail(c, li))
    assert calls["n"] == 1
    assert li.year_built is None
