"""Charleston delinquent-tax scraper: a THIRD FLC document was being silently
skipped (docs/coverage_gap_build_plan_2026-09-23.md item 7).

`_discover_pdfs` originally split every .pdf link on the landing page two ways:
a "tax-sale-listing"/"/(rp|mh)tax" data file, or a "sealed-bid" + ("form" or
"submittal") blank FORM (recorded as metadata only, never parsed). Live-read
2026-09-23 (https://www.charlestoncounty.gov/departments/delinquent-tax/
tax-sale.php): a real third document, "FLC-Properties-for-Sealed-Bid-TS2025.pdf",
sits on the same page and matches NEITHER branch -- it isn't named like the RP/MH
listings, and it isn't a blank form (own pdfplumber table, real rows) -- so it
fell through both branches and was never fetched.

FETCHED AND PARSED LIVE, 2026-09-23 (saved verbatim as this repo's own fixture,
tests/fixtures/charleston_flc_properties_for_sealed_bid_ts2025.pdf, HTTP 200,
28,576 bytes, application/pdf): pdfplumber finds one real table, one page,
header ``OWNER NAME | TMS | SITUS | FLC BID AMT``, 4 data rows:

    78 DEVEREAUX AVE     3400000040   714 RIVERLAND          $2,112.63
    BROWN DORIS          6280000122   0 WINDWOOD FARMS RD    $7,654.03
    RUSSELL JOHN V JR    3850200048   114 JANDRELL RD         $586.20
    SANDERS ISAAC        7120000167   8546 N HIGHWAY 17       $742.20

These are parcels that already went through Charleston's annual tax sale unsold
and are now FLC inventory offered by sealed bid -- genuinely different (further-
along) inventory from the pre-sale RP/MH-Tax-Sale-Listing.pdf this scraper
already reads, not a duplicate.

THE FIX has two parts:
  1. `_discover_pdfs` now also matches "sealed-bid" + "properties" (present in
     this filename, absent from the two blank-form filenames) into the parsed
     `lists` bucket instead of leaving it unmatched.
  2. `_HDR_PIN`/`_HDR_DUE`/`_is_header_row` now also accept this document's
     "TMS"/"FLC BID AMT" column labels alongside the RP/MH listings' "pin"/
     "Totaldue" -- `parse_listing_pdf` itself needed no other change since it is
     already header-driven, not filename-driven, for column mapping.

NOT wired: the same landing page also links "Sealed-Bid-list.xlsx"/".pdf", whose
own title cell reads "2022 TAX SALE SEALED BID SALE" -- 4 years stale relative to
this run -- so it is deliberately left alone rather than risking a speculative
re-ingest of old inventory as current (see this file's own probe notes in
docs/coverage_gap_build_plan_2026-09-23.md's item 7 follow-up, and
_discover_pdfs's own docstring).

The fixture PDF is fetched live in this test (no network mocking) since it's a
small (28KB), already-downloaded, saved copy -- this proves the real bytes parse,
not just a hand-typed approximation of them.
"""
from __future__ import annotations

from pathlib import Path

from foreclosure_scraper.scrapers.counties_sc.charleston_delinquent_tax import (
    _discover_pdfs,
    _is_header_row,
    parse_listing_pdf,
)

FIXTURES = Path(__file__).parent / "fixtures"

# Real hrefs, verbatim, from the live tax-sale.php landing page, 2026-09-23.
_LANDING_HTML = """
<html><body>
<a href="https://www.charlestoncounty.gov/departments/delinquent-tax/files/tax_sale/RP-Tax-Sale-Listing.xlsx?v=640">RP xlsx</a>
<a href="https://www.charlestoncounty.gov/departments/delinquent-tax/files/RP-Tax-Sale-Listing.pdf?v=640">RP pdf</a>
<a href="https://www.charlestoncounty.gov/departments/delinquent-tax/files/MH-Tax-Sale-Listing.pdf?v=640">MH pdf</a>
<a href="https://www.charlestoncounty.gov/departments/delinquent-tax/files/FLC-Properties-for-Sealed-Bid-TS2025.pdf?v=640">FLC properties</a>
<a href="https://www.charlestoncounty.gov/departments/delinquent-tax/files/FLC-Sealed-Bid-Form.pdf?v=640">FLC form</a>
<a href="https://www.charlestoncounty.gov/departments/delinquent-tax/files/FLC-Sealed-Bid-Submittal-Form-12-08-2025-Tax-Sale.pdf?v=640">FLC submittal form</a>
<a href="https://www.charlestoncounty.gov/departments/delinquent-tax/files/FLC-Instructions.pdf?v=640">FLC instructions</a>
<a href="https://www.charlestoncounty.gov/departments/delinquent-tax/files/Sealed-Bid-list.pdf?v=640">Sealed bid list (stale)</a>
</body></html>
"""


def test_discover_pdfs_now_includes_the_flc_properties_list():
    lists, form = _discover_pdfs(_LANDING_HTML)
    flc_properties = [u for u in lists if "flc-properties-for-sealed-bid" in u.lower()]
    assert len(flc_properties) == 1
    assert "ts2025" in flc_properties[0].lower()


def test_discover_pdfs_still_separates_the_blank_forms():
    lists, form = _discover_pdfs(_LANDING_HTML)
    # The two blank submittal forms must NOT end up in the parsed-list bucket.
    assert not any("form" in u.lower() or "submittal" in u.lower() for u in lists)
    assert form is not None
    assert "sealed-bid-form" in form.lower()


def test_discover_pdfs_still_finds_rp_and_mh_listings():
    lists, _ = _discover_pdfs(_LANDING_HTML)
    assert any("rp-tax-sale-listing" in u.lower() for u in lists)
    assert any("mh-tax-sale-listing" in u.lower() for u in lists)


def test_discover_pdfs_ignores_the_stale_sealed_bid_list():
    # "Sealed-Bid-list.pdf" has neither "properties" (so it misses the new FLC-
    # properties branch) nor "form"/"submittal" (so it misses the form branch)
    # -- it is correctly ignored by both, matching the module docstring's
    # explicit "not wired, stale" decision.
    lists, form = _discover_pdfs(_LANDING_HTML)
    assert not any("sealed-bid-list" in u.lower() for u in lists)
    assert not (form and "sealed-bid-list" in form.lower())


def test_is_header_row_accepts_tms_and_flc_bid_amt():
    assert _is_header_row(["OWNER NAME", "TMS", "SITUS", "FLC BID AMT"])
    # Existing RP/MH header shape must still be recognised.
    assert _is_header_row(["pin", "classcd", "owner1", "owner2"])


def test_real_flc_properties_pdf_parses_into_four_real_listings():
    data = (FIXTURES / "charleston_flc_properties_for_sealed_bid_ts2025.pdf").read_bytes()
    assert data[:4] == b"%PDF"
    listings = parse_listing_pdf(
        data,
        "https://www.charlestoncounty.gov/departments/delinquent-tax/files/"
        "FLC-Properties-for-Sealed-Bid-TS2025.pdf",
    )
    assert len(listings) == 4
    by_pin = {li.parcel_id: li for li in listings}
    assert set(by_pin) == {"3400000040", "6280000122", "3850200048", "7120000167"}

    doris = by_pin["6280000122"]
    assert doris.defendant == "BROWN DORIS"
    assert doris.street_address == "0 WINDWOOD FARMS RD"
    assert doris.opening_bid == 7654.03
    assert doris.state == "SC" and doris.county == "Charleston"
    from foreclosure_scraper.models import ListingType
    assert doris.listing_type == ListingType.TAX_SALE
    # No per-parcel or header sale date on this list -- it's standing FLC
    # inventory, not a scheduled auction.
    assert doris.sale_date is None
    assert doris.raw["charleston_delinquent_tax"]["dateless"] is True

    sanders = by_pin["7120000167"]
    assert sanders.defendant == "SANDERS ISAAC"
    assert sanders.street_address == "8546 N HIGHWAY 17"
    assert sanders.opening_bid == 742.20
