"""Pin the judgment-amount detail-page fetcher (dad's #5 follow-up).

This module fetches per-listing detail pages (URL already captured
as source_url by the law-firm scrapers) and re-runs the
judgment_amount extractor on the fetched Notice of Sale text. We
mock httpx to avoid live fetches.

Tests cover: URL-pattern gating, source-allowlist gating, priority
sort, fetch-and-extract happy path, cap respect, idempotency
(don't re-fetch already-set listings), graceful handling of fetch
failures.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from foreclosure_scraper.enrichment_judgment_detail import (
    _looks_like_detail_page,
    _priority,
    enrich_judgment_amount_via_detail_pages,
)
from foreclosure_scraper.models import Listing, ListingType


def _li(**kw) -> Listing:
    base = dict(
        source="law_firms.brock_scott",
        source_url="https://brockandscott.com/foreclosure-sale/abc-123/",
        listing_type=ListingType.FORECLOSURE_SALE,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


# ---- URL gating ----

def test_url_pattern_accepts_per_listing_detail():
    assert _looks_like_detail_page("https://brockandscott.com/foreclosure-sale/abc-123/")
    assert _looks_like_detail_page("https://brockandscott.com/foreclosure-sale/12345")


def test_url_pattern_accepts_sales_list_aspx():
    """Hutchens lists everything on one /NCfcSalesList.aspx page —
    we accept it since rows on that page contain full notice text."""
    assert _looks_like_detail_page("https://sales.hutchenslawfirm.com/NCfcSalesList.aspx")


def test_url_pattern_rejects_homepage():
    assert not _looks_like_detail_page("https://example.com/")
    assert not _looks_like_detail_page("https://example.com")


def test_url_pattern_rejects_none():
    assert not _looks_like_detail_page(None)
    assert not _looks_like_detail_page("")


# ---- priority ----

def test_priority_imminent_first():
    """Imminent (sale in 0-14 days) sorts before farther-out sales."""
    now = datetime.utcnow()
    imminent = _li(sale_date=now + timedelta(days=5))
    medium = _li(sale_date=now + timedelta(days=45))
    past = _li(sale_date=now - timedelta(days=3))
    nodate = _li()
    items = [nodate, past, medium, imminent]
    items.sort(key=_priority)
    assert items[0] is imminent
    assert items[-1] is nodate


# ---- dispatch happy path ----

@pytest.mark.asyncio
async def test_dispatch_fetches_eligible_listings():
    """Eligible listing → fetch detail page → extract judgment_amount."""
    # Padded to >500 chars so the real-page sanity threshold passes
    fake_html = ("<html><body>"
                 + "Notice of Sale of Real Property. " * 30
                 + "<p>Pursuant to a judgment entered in the General Court, the"
                 " judgment amount of $125,750.00 was entered against defendants.</p>"
                 + "Description of property: lot 4 ..." * 5
                 + "</body></html>")

    class FakeResp:
        status_code = 200
        text = fake_html

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return FakeResp()

    li = _li()
    with patch("httpx.AsyncClient", lambda *a, **kw: FakeClient()):
        stats = await enrich_judgment_amount_via_detail_pages([li])

    assert stats["candidates"] == 1
    assert stats["fetched"] == 1
    assert stats["matched"] == 1
    assert li.judgment_amount == 125_750.00


@pytest.mark.asyncio
async def test_already_set_listings_skipped():
    """Listings with judgment_amount already populated → not eligible."""
    li_done = _li(judgment_amount=99_000.0)
    li_pending = _li()

    class FakeResp:
        status_code = 200
        text = "<html><body>" + ("Notice of Sale " * 50) + "judgment amount of $50,000.00" + ("padding " * 50) + "</body></html>"

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return FakeResp()

    with patch("httpx.AsyncClient", lambda *a, **kw: FakeClient()):
        stats = await enrich_judgment_amount_via_detail_pages([li_done, li_pending])

    assert stats["candidates"] == 1  # only li_pending
    assert li_done.judgment_amount == 99_000.0  # untouched


@pytest.mark.asyncio
async def test_unsupported_source_skipped():
    """A listing from a scraper not in _DETAIL_PAGE_SOURCES is skipped."""
    li = _li(source="counties_nc.polk_tax")
    stats = await enrich_judgment_amount_via_detail_pages([li])
    assert stats["candidates"] == 0


@pytest.mark.asyncio
async def test_bad_url_skipped():
    """Source listed but URL doesn't look like a detail page → skip."""
    li = _li(source_url="https://brockandscott.com/about/")
    stats = await enrich_judgment_amount_via_detail_pages([li])
    assert stats["candidates"] == 0


@pytest.mark.asyncio
async def test_cap_respected():
    """max_fetches caps the number of HTTP requests."""
    listings = [
        _li(source_url=f"https://brockandscott.com/foreclosure-sale/x{i}/")
        for i in range(10)
    ]

    class FakeResp:
        status_code = 200
        text = "<html><body>" + "x" * 1000 + "</body></html>"

    class FakeClient:
        get_calls = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw):
            FakeClient.get_calls += 1
            return FakeResp()

    with patch("httpx.AsyncClient", lambda *a, **kw: FakeClient()):
        stats = await enrich_judgment_amount_via_detail_pages(listings, max_fetches=3)

    assert stats["candidates"] == 10
    assert stats["skipped_capped"] == 7
    assert stats["fetched"] == 3
    assert FakeClient.get_calls == 3


@pytest.mark.asyncio
async def test_fetch_404_handled_gracefully():
    """A 404 response → no crash, count as fetched-but-no-match."""
    class FakeResp:
        status_code = 404
        text = "Not Found"

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return FakeResp()

    li = _li()
    with patch("httpx.AsyncClient", lambda *a, **kw: FakeClient()):
        stats = await enrich_judgment_amount_via_detail_pages([li])
    assert stats["fetched"] == 0
    assert stats["matched"] == 0
    assert li.judgment_amount is None


@pytest.mark.asyncio
async def test_fetch_text_without_judgment_phrase_no_match():
    """Fetched OK but page has no judgment-amount phrasing → no match."""
    class FakeResp:
        status_code = 200
        text = "<html><body>" + ("just some random text about a property " * 50) + "</body></html>"

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return FakeResp()

    li = _li()
    with patch("httpx.AsyncClient", lambda *a, **kw: FakeClient()):
        stats = await enrich_judgment_amount_via_detail_pages([li])
    assert stats["fetched"] == 1
    assert stats["matched"] == 0
    assert li.judgment_amount is None
    # Even on no-match, the fetched text is cached in raw for future runs
    assert li.raw.get("detail_page", {}).get("text") is not None


@pytest.mark.asyncio
async def test_no_candidates_returns_empty_stats():
    """All listings filtered out → stats with candidates=0, no fetch attempted."""
    li = _li(judgment_amount=50_000)  # already set
    stats = await enrich_judgment_amount_via_detail_pages([li])
    assert stats["candidates"] == 0
    assert stats["fetched"] == 0


@pytest.mark.asyncio
async def test_matched_by_source_breakdown():
    """When multiple sources match, by_source_matched counts each."""
    fake_html = "<html><body>" + ("Notice of Sale " * 50) + "judgment amount of $100,000" + ("padding " * 50) + "</body></html>"

    class FakeResp:
        status_code = 200
        text = fake_html

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return FakeResp()

    a = _li(source="law_firms.brock_scott",
            source_url="https://brockandscott.com/foreclosure-sale/x/")
    b = _li(source="law_firms.hutchens",
            source_url="https://sales.hutchenslawfirm.com/NCfcSalesList.aspx")
    with patch("httpx.AsyncClient", lambda *a, **kw: FakeClient()):
        stats = await enrich_judgment_amount_via_detail_pages([a, b])
    assert stats["matched"] == 2
    assert stats["matched_by_source"]["law_firms.brock_scott"] == 1
    assert stats["matched_by_source"]["law_firms.hutchens"] == 1
