"""reo.treasury_seized: a transient transport error on either real network call gets
retried, not treated as a real fetch failure.

Both of this module's two external calls -- fetch()'s list-page GET (the ONLY source of
every listing this scraper can produce) and _enrich_from_detail()'s per-listing detail-page
GET -- go through the shared http_client.client() context manager directly with a bare
`.get()`. client()'s own docstring says "retries=0 removes the transport's connect-retry
amplification -- callers already wrap their own AsyncRetrying", and neither call site did.
A single transient TCP reset/timeout on the list-page call would zero this run's whole
output, and because this source is registered in main.DATELESS_OK_SOURCES (no fallback date
window) that zero can't self-heal later -- it looks identical to a genuinely empty week.
Same root cause, same fix, as the Column legal-notice API scraper, spartan_weekly_legals.py,
and arcgis_webmap.query_features() earlier the same night.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.reo import treasury_seized as M

# A minimal but valid list page: one NC address ADDR_RE matches, no detail link (so these
# tests exercise fetch()'s own retry wrapper in isolation, without also fetching a detail
# page). Padded well past the real page's own >1000-char floor.
LIST_HTML = (
    "<html><body><p>123 Test Street, Testville, North Carolina 27500</p></body></html>"
    + " " * 1200
)

# A minimal detail page carrying the one field _enrich_from_detail's headline fix cares
# about (opening_bid -- the list page never shows a price at all; see the module's own
# docstring finding #2), padded past the real method's own >500-char floor.
DETAIL_HTML = (
    "<html><body><div>Starting Bid:</div><div>$100,000</div></body></html>" + " " * 500
)


def _fake_client(get_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        yield stub
    return _cm


def _make_listing() -> "M.Listing":
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind
    return Listing(
        source="reo.treasury_seized",
        source_url=M.URL,
        listing_type=ListingType.REO,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        street_address="123 Test Street",
        city="Testville",
        zip_code="27500",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"treasury_seized": {"forward_excerpt": "x"}},
    )


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        M, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


# --- fetch() -- the list-page call (primary finding, site 1) ----------------------------


def test_fetch_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return MagicMock(status_code=200, text=LIST_HTML)

    monkeypatch.setattr(M, "client", _fake_client(get))
    out = asyncio.run(M.TreasurySeizedRealProperty().fetch())
    assert calls["n"] == 3
    assert len(out) == 1
    assert out[0].street_address == "123 Test Street"


def test_fetch_a_connect_timeout_that_never_clears_still_ends_cleanly_not_hangs(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    out = asyncio.run(asyncio.wait_for(M.TreasurySeizedRealProperty().fetch(), timeout=5.0))
    assert calls["n"] == 3   # stop_after_attempt(3), then gives up gracefully -- no hang
    assert out == []


def test_fetch_a_real_500_on_the_list_page_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        return MagicMock(status_code=500, text="error")

    monkeypatch.setattr(M, "client", _fake_client(get))
    out = asyncio.run(M.TreasurySeizedRealProperty().fetch())
    assert calls["n"] == 1   # a real bad status is not a transport/timeout error
    assert out == []


# --- _enrich_from_detail() -- the per-listing detail-page call (secondary finding, site 2) -


def test_enrich_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return MagicMock(status_code=200, text=DETAIL_HTML)

    monkeypatch.setattr(M, "client", _fake_client(get))
    li = _make_listing()
    scraper = M.TreasurySeizedRealProperty()
    asyncio.run(scraper._enrich_from_detail(li, "https://www.treasury.gov/auctions/treasury/rp/x.shtml"))
    assert calls["n"] == 3
    assert li.opening_bid == 100000.0


def test_enrich_a_connect_timeout_that_never_clears_still_ends_cleanly_not_hangs(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    li = _make_listing()
    scraper = M.TreasurySeizedRealProperty()
    asyncio.run(asyncio.wait_for(
        scraper._enrich_from_detail(li, "https://www.treasury.gov/auctions/treasury/rp/x.shtml"),
        timeout=5.0,
    ))
    assert calls["n"] == 3   # stop_after_attempt(3), then gives up gracefully -- no hang
    assert li.opening_bid is None   # the base listing's own fields are left untouched


def test_enrich_a_real_500_on_the_detail_page_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, **kw):
        calls["n"] += 1
        return MagicMock(status_code=500, text="error")

    monkeypatch.setattr(M, "client", _fake_client(get))
    li = _make_listing()
    scraper = M.TreasurySeizedRealProperty()
    asyncio.run(scraper._enrich_from_detail(li, "https://www.treasury.gov/auctions/treasury/rp/x.shtml"))
    assert calls["n"] == 1   # a real bad status is not a transport/timeout error
    assert li.opening_bid is None
