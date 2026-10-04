"""newspapers.berkeley_independent — scope-gate + volume-cap regression.

FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 1):
identical root cause and fix as the sibling newspapers.aiken_standard (same
Post & Courier TownNews backend, same shared parser) -- Berkeley County has
never been in the 18-county flip footprint, so every ListingType.
FORECLOSURE_SALE row was silently dropped by main._flip_outside_footprint().
Remapped to LIS_PENDENS in this file's fetch() wrapper. Also bumped the feed
l=50 cap to the real server max l=100 (confirmed live: 74 rows at l=100 vs 50
at l=50 for the "foreclosure" query alone -- 25 real, current rows were never
fetched at all).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import main
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.newspapers import berkeley_independent as mod

# Real captured shape (Berkeley Independent, 2026-10-04).
BERKELEY_RSS = """<rss><channel>
<item>
<title>STATE OF SOUTH CAROLINA COUNTY OF BERKELEY IN THE COURT OF COMMON PLEAS CASE NO.: 2025-CP-08-00027 NOTICE OF SALE</title>
<link>https://www.postandcourier.com/berkeley-independent/classifieds/community/announcements/legal/ad_berk.html</link>
<description>STATE OF SOUTH CAROLINA COUNTY OF BERKELEY IN THE COURT OF COMMON PLEAS CASE NO.: 2025-CP-08-00027 NOTICE OF SALE BY VIRTUE of a decree heretofore granted in the case of: Freedom Mortgage Corporation against John Doe</description>
<pubDate>Wed, 30 Sep 2026 00:30:02 -0400</pubDate>
</item>
</channel></rss>"""


def _run_fetch(monkeypatch, xml: str):
    async def fake_get_text(url, timeout=30.0):
        return xml

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    return asyncio.run(mod.BerkeleyIndependentForeclosures().fetch())


def test_foreclosure_sale_remapped_to_lis_pendens(monkeypatch):
    out = _run_fetch(monkeypatch, BERKELEY_RSS)
    assert len(out) == 1
    assert out[0].listing_type == ListingType.LIS_PENDENS
    assert out[0].county == "Berkeley"


def test_remapped_row_passes_real_in_scope_gate(monkeypatch):
    out = _run_fetch(monkeypatch, BERKELEY_RSS)
    assert len(out) == 1
    assert main._in_scope(out[0]) is True


def test_unfixed_foreclosure_sale_type_is_unreachable():
    from foreclosure_scraper.models import Listing, PropertyKind
    from datetime import datetime, UTC

    li = Listing(
        source="newspapers.berkeley_independent",
        source_url="https://example.com/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Berkeley",
        street_address="123 Test St",
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        raw={},
    )
    assert main._in_scope(li) is False


def test_feed_urls_use_real_server_max():
    for url in mod.FEED_URLS:
        assert "l=100" in url
        assert "l=50" not in url


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    assert "newspapers.berkeley_independent" in {s.slug for s in all_scrapers()}
