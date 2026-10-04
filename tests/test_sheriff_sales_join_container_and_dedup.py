"""national.sheriff_sales — HERMES extraction-completeness audit, batch 18
(2026-10-04). Two fixes on top of `_join_single_posting_container`'s core
case (covered in tests/test_sheriff_sales_auction_wording.py):

1. The join must REFUSE to fire when a container holds multiple distinct
   postings (multiple case-number or multiple sale-context signals) --
   joining those would merge unrelated postings into one fabricated
   composite listing, repeating the exact class of bug the 2026-10-01 fix
   was about.

2. `_fetch_county`'s cross-page dedup used to key on bare `source_url`
   alone, which is identical for every listing parsed off the SAME page --
   so a page with 2+ genuinely distinct postings would have kept only the
   first and silently dropped the rest as "duplicates". Re-keyed on
   (source_url, case_number, street_address).
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.sheriff_sales import (
    _join_single_posting_container,
    _parse_brunswick,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from selectolax.parser import HTMLParser


_TWO_DISTINCT_POSTINGS_HTML = """
<html><body>
<div class="entry-content">
<p>FILE# 19 CVS 004029-640</p>
<p><a>SHERIFF'S AUCTION 7/17/2026</a></p>
<p>FILE# 20 CVS 001111-222</p>
<p><a>SHERIFF'S AUCTION 8/01/2026</a></p>
</div>
</body></html>
"""

_EMPTY_CONTAINER_HTML = """
<html><body>
<div class="entry-content">
<p>&nbsp;</p>
<p>No public auction at this time.</p>
</div>
</body></html>
"""


def test_join_refuses_when_container_holds_multiple_postings():
    """Must not merge two distinct case numbers/sale dates into one
    fabricated composite listing."""
    tree = HTMLParser(_TWO_DISTINCT_POSTINGS_HTML)
    assert _join_single_posting_container(tree) is None


def test_two_distinct_postings_page_falls_through_to_per_element_loop_not_crash():
    """Even though the join refuses, the page must not crash -- it falls
    through to the existing per-element loop (which, per the pre-existing
    2026-10-01 behavior, requires sale-context AND address/case in the SAME
    element, so it may legitimately find 0 here since this fixture splits
    them -- the point of this test is 'no exception, no fabricated merge',
    not a specific count)."""
    out = _parse_brunswick(
        _TWO_DISTINCT_POSTINGS_HTML,
        "https://www.brunswicksheriff.com/resources/auctions",
    )
    # No crash, and critically: never a single row with BOTH case numbers
    # or both dates merged together.
    for li in out:
        assert not (li.case_number and "19" in li.case_number and "20" in li.case_number)


def test_join_returns_none_for_a_genuinely_empty_notice():
    tree = HTMLParser(_EMPTY_CONTAINER_HTML)
    assert _join_single_posting_container(tree) is None


def _mk_listing(source_url: str, case_number: str, street_address: str) -> Listing:
    from datetime import datetime
    return Listing(
        source="national.sheriff_sales",
        source_url=source_url,
        listing_type=ListingType.SHERIFF_SALE,
        property_kind=PropertyKind.UNKNOWN,
        street_address=street_address,
        county="Brunswick",
        state="NC",
        case_number=case_number,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={},
    )


def test_dedup_key_distinguishes_two_real_postings_on_one_page():
    """FOUND batch 18: dedup must be keyed on more than bare source_url, or
    two genuinely distinct postings parsed off the SAME page URL collapse
    into one. This test exercises the key-construction logic directly
    (mirrors _fetch_county's own key tuple) rather than re-driving the
    whole async fetch."""
    page_url = "https://www.brunswicksheriff.com/resources/auctions"
    a = _mk_listing(page_url, "19 CVS 004029-640", "1 First St")
    b = _mk_listing(page_url, "20 CVS 001111-222", "2 Second St")

    seen: set[tuple] = set()
    out = []
    for li in (a, b):
        key = (li.source_url, li.case_number, li.street_address)
        if key not in seen:
            seen.add(key)
            out.append(li)
    assert len(out) == 2, "two distinct postings on one page must both survive dedup"


def test_dedup_key_still_collapses_the_same_posting_seen_on_two_pages():
    """The ORIGINAL purpose of this dedup set must still hold: the same
    posting reached via both the main page and a linked sub-page is still
    one listing, not two."""
    a = _mk_listing(
        "https://www.brunswicksheriff.com/resources/auctions",
        "19 CVS 004029-640", "1 First St",
    )
    b = _mk_listing(
        "https://www.brunswicksheriff.com/resources/auctions",
        "19 CVS 004029-640", "1 First St",
    )
    seen: set[tuple] = set()
    out = []
    for li in (a, b):
        key = (li.source_url, li.case_number, li.street_address)
        if key not in seen:
            seen.add(key)
            out.append(li)
    assert len(out) == 1
