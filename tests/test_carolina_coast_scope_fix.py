"""newspapers.carolina_coast — scope-gate + volume-cap regression.

FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 1):
Carteret County is NOT in the 18-county WNC+Upstate-SC flip footprint (though
it IS in main.OCEANFRONT_COASTAL_COUNTIES). The shared _townnews._classify()
returns ListingType.FORECLOSURE_SALE for the NC substitute-trustee template
this feed is dominated by, and main._flip_outside_footprint() rejects any
flip-type row outside the footprint UNCONDITIONALLY -- before the oceanfront
carve-out even runs. Confirmed live: both of 2 real current rows today
classified FORECLOSURE_SALE. Remapped to LIS_PENDENS in this file's fetch()
wrapper (scoped here only; _townnews._classify() itself is untouched since
post_and_courier.py/journal_scene.py/index_journal.py share it and were not
re-verified this batch). Also bumped the feed l=50 cap to the real server max
l=100 (low practical impact given this paper's tiny real volume, but kept
consistent with the sibling Post & Courier-network papers).

See tests/test_townnews_legal_notices.py for the shared-parser-level tests
(address/case-number/county extraction); this file covers only the
fetch()-wrapper-level scope fix added on top of that.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import main
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.newspapers import carolina_coast as mod

# Real captured shape (Carolina Coast / Carteret NC, 2026-10-04).
CC_RSS = """<rss><channel>
<item>
<title>NOTICE OF FORECLOSURE SALE 25SP001124-150 168 BAYBERRY RD NEWPORT, NC</title>
<link>https://www.carolinacoastonline.com/classifieds/community/announcements/legal/ad_cc.html</link>
<description>NOTICE OF FORECLOSURE SALE 25SP001124-150 168 BAYBERRY RD NEWPORT, NC Under and by virtue of the power of sale contained in that certain Deed of Trust executed by Jane Doe</description>
<pubDate>Sun, 04 Oct 2026 00:00:00 -0400</pubDate>
</item>
</channel></rss>"""


def _run_fetch(monkeypatch, xml: str):
    async def fake_get_text(url, timeout=30.0):
        return xml

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    return asyncio.run(mod.CarolinaCoastForeclosures().fetch())


def test_foreclosure_sale_remapped_to_lis_pendens(monkeypatch):
    out = _run_fetch(monkeypatch, CC_RSS)
    assert len(out) == 1
    assert out[0].listing_type == ListingType.LIS_PENDENS
    assert out[0].county == "Carteret"


def test_remapped_row_passes_real_in_scope_gate(monkeypatch):
    out = _run_fetch(monkeypatch, CC_RSS)
    assert len(out) == 1
    assert main._in_scope(out[0]) is True


def test_unfixed_foreclosure_sale_type_is_unreachable_even_though_coastal():
    """Carteret IS in main.OCEANFRONT_COASTAL_COUNTIES, but
    _flip_outside_footprint() rejects a flip-type row BEFORE that carve-out
    can run -- "however it got its coastal credentials" per its own
    docstring. Confirms the type remap, not county/coastal status, is what
    was blocking every row."""
    from foreclosure_scraper.models import Listing, PropertyKind
    from datetime import datetime, UTC

    li = Listing(
        source="newspapers.carolina_coast",
        source_url="https://example.com/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Carteret",
        street_address="168 Bayberry Rd",
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

    assert "newspapers.carolina_coast" in {s.slug for s in all_scrapers()}
