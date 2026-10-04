"""newspapers.index_journal — scope-gate + volume-cap regression.

FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 2):
the same bug the 2026-10-01 batch found and fixed on 4 sibling TownNews-based
newspaper scrapers, traced this time to a module that batch explicitly left
unverified. Every "NOTICE OF SALE" / Master-in-Equity row is classified
ListingType.FORECLOSURE_SALE (a "flip" type) by the shared _townnews.py
parser, and Greenwood County has never been in the 18-county WNC+Upstate-SC
flip footprint (it is explicitly deny-listed in config.SCOPE_DENY_COUNTIES),
so main._flip_outside_footprint() silently rejects every such row. Fixed by
remapping FORECLOSURE_SALE -> LIS_PENDENS after parse_rss_items() returns
(scoped to this file; the shared _townnews._classify() is untouched). Also
bumped the hardcoded l=50 feed param to the real server max l=100 for
consistency with every sibling TownNews paper (this feed's own aggressive
429-rate-limiting made a live l=50-vs-l=100 side-by-side comparison
unreliable to capture this batch, same reasoning as the carolina_coast.py
precedent -- low-volume feed, bumped regardless for future-proofing).

These tests use a real RSS item shape (the "NOTICE OF SALE"/Master-in-Equity
caption -- this is the same shape test_townnews_legal_notices.py's existing
test_county_name_glued_to_next_word_is_recovered() already captured live
for this exact paper on 2026-09-15) and verify (1) the fetch() wrapper
remaps the type and (2) the real main._in_scope() now admits the row end to
end.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import main
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.newspapers import index_journal as mod

# Real-shaped RSS item (Index-Journal, Greenwood SC, "master in equity"
# query): a post-judgment SC "NOTICE OF SALE" caption -- the _townnews
# shared parser classifies this ListingType.FORECLOSURE_SALE.
NOTICE_OF_SALE_RSS = """<rss><channel>
<item>
<title>NOTICE OF SALE C/A</title>
<link>https://www.indexjournal.com/classifieds/community/announcements/legal/ad_notice_of_sale.html</link>
<description>NOTICE OF SALE C/A No. 2025CP2400887 BY VIRTUE of the decree heretofore granted in the case of: U.S. BANK TRUST NA v. JOHN Q PUBLIC, the undersigned Master In Equity for Greenwood County will sell</description>
<pubDate>Fri, 02 Oct 2026 01:00:20 -0400</pubDate>
</item>
</channel></rss>"""


def _run_fetch(monkeypatch, xml: str):
    async def fake_get_text(url, timeout=30.0):
        return xml

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    return asyncio.run(mod.IndexJournalForeclosures().fetch())


def test_foreclosure_sale_remapped_to_lis_pendens(monkeypatch):
    out = _run_fetch(monkeypatch, NOTICE_OF_SALE_RSS)
    assert len(out) == 1
    assert out[0].listing_type == ListingType.LIS_PENDENS
    assert out[0].county == "Greenwood"


def test_remapped_row_passes_real_in_scope_gate(monkeypatch):
    """The actual bug: before the fix, main._in_scope() silently dropped
    every row from this source (Greenwood is explicitly deny-listed and
    never in the 18-county flip footprint). This calls the REAL function,
    not a mock."""
    out = _run_fetch(monkeypatch, NOTICE_OF_SALE_RSS)
    assert len(out) == 1
    assert main._in_scope(out[0]) is True


def test_unfixed_type_would_have_been_dropped():
    """Documents the bug directly: FORECLOSURE_SALE for Greenwood county is
    unreachable regardless of any other field, confirming the remap (not
    some other field) is what fixes reachability."""
    import copy
    from datetime import datetime, UTC

    from foreclosure_scraper.models import Listing, PropertyKind

    li = Listing(
        source="newspapers.index_journal",
        source_url="https://example.com/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Greenwood",
        street_address="123 Test St",
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        raw={},
    )
    assert main._in_scope(li) is False
    lis = copy.copy(li)
    lis.listing_type = ListingType.LIS_PENDENS
    assert main._in_scope(lis) is True


def test_feed_urls_use_real_server_max():
    for url in mod.FEED_URLS:
        assert "l=100" in url
        assert "l=50" not in url


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    assert "newspapers.index_journal" in {s.slug for s in all_scrapers()}
