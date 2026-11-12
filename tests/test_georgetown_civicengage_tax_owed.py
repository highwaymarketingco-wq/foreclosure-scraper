"""Georgetown County (SC) CivicEngage FLC list — opening-bid capture.

2026-09-29 audit finding: counties_sc.georgetown_civicengage (355 board rows) was
flagged as capturing NO real per-parcel tax amount at all. Root cause was narrower
than that: the FLC (Forfeited-Land-Commission) doc's parser already captured a
real, county-published dollar figure onto Listing.opening_bid, but never wrote it
into the raw block, so enrichment_tax_owed.py (which reads raw sub-dicts, not
Listing fields) could never see it -- and even if it had, "georgetown_civicengage"
wasn't in that module's per-source mapping. Fixed by writing opening_bid into the
raw block AND adding the mapping entry (see enrichment_tax_owed.py's _SOURCES).

The Tax-Sale doc (300 of the 355 rows) is a genuinely different case: confirmed
live 2026-09-29 that Georgetown's own "2025 Tax Sale List (PDF)" carries zero "$"
characters anywhere across its 24 pages -- there is no dollar figure to extract.
That gap is documented in docs/extraction_gaps.md, not fixed here.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc.georgetown_civicengage import (
    parse_flc,
    parse_tax,
)

_FLC_LINE = (
    "5028 Baker Louise (H) 01-0442-029-03-00.001 1973 12x45 Panoramic "
    "11/1/2021 $901.77"
)

_TAX_LINE = "ANDREWS LARRY A 05-0017-114-00-00 2024-1010302-0"


def test_flc_opening_bid_lands_on_the_listing_field():
    rows = parse_flc(_FLC_LINE, "https://example/flc.pdf")
    assert len(rows) == 1
    assert rows[0].opening_bid == 901.77


def test_flc_opening_bid_is_also_duplicated_into_the_raw_block():
    """enrichment_tax_owed.py reads raw sub-dicts, never Listing fields directly,
    so the amount has to be duplicated here for the tax_owed waterfall to see it."""
    rows = parse_flc(_FLC_LINE, "https://example/flc.pdf")
    blk = rows[0].raw["georgetown_civicengage"]
    assert blk["doc"] == "flc"
    assert blk["opening_bid"] == 901.77


def test_tax_sale_doc_carries_no_amount_field():
    """The Tax-Sale list has no dollar column on the source PDF at all (confirmed
    live 2026-09-29) -- parse_tax must not fabricate one."""
    rows = parse_tax(_TAX_LINE, "https://example/tax.pdf")
    assert len(rows) == 1
    assert rows[0].opening_bid is None
    blk = rows[0].raw["georgetown_civicengage"]
    assert "opening_bid" not in blk
