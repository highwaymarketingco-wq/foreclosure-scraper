"""public_notices.ncnotices — stale out-of-footprint county scope-gate fix.

FOUND 2026-10-04 (HERMES extraction-completeness audit, public_notices
batch): COUNTY_RE still carries Mecklenburg/Madison/Yancey -- stale
leftovers from before the 2026-05-07 footprint narrowing (none of the 3 are
in config.NC_COUNTIES, and all 3 are explicitly in config.SCOPE_DENY_
COUNTIES today). ListingType.FORECLOSURE_SALE/SHERIFF_SALE (the two flip
types _classify() can produce for the "foreclosure" category) are gated to
the narrow 18-county footprint by main._flip_outside_footprint(), checked
before every other admission path -- so a Mecklenburg/Madison/Yancey
foreclosure-sale notice (a real, plausible occurrence: Mecklenburg is NC's
largest county) was silently dropped at the board gate every time.

Fixed by remapping FORECLOSURE_SALE/SHERIFF_SALE -> LIS_PENDENS in
_parse_results_html() whenever the resolved county is outside the true
18-county flip footprint; the 11 real footprint counties are unaffected.
"""
from __future__ import annotations

from foreclosure_scraper import main
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.public_notices.ncpublicnotices import (
    _parse_results_html,
)

_HTML_TEMPLATE = """<html><body>
<div id="ctl00_ContentPlaceHolder1_WSExtendedGridNP1_updateWSGrid">
<table><tr class="searchResultRow"><td>
NORTH CAROLINA {county} COUNTY NOTICE OF FORECLOSURE SALE under and by virtue of the
power of sale contained in that certain Deed of Trust executed by John Q Public,
Substitute Trustee will sell at public auction the property located at 123 Main Street,
Anytown, NC 28801 on November 1, 2026.
<a href="/Details.aspx?ID=12345">View</a>
</td></tr></table></div></body></html>"""


def _rows_for(county: str):
    html = _HTML_TEMPLATE.format(county=county.upper())
    return _parse_results_html(html, "foreclosure sale", "foreclosure")


def test_stale_out_of_footprint_counties_are_remapped_and_reach_the_board():
    for county in ("Mecklenburg", "Madison", "Yancey"):
        rows = _rows_for(county)
        assert len(rows) == 1, county
        li = rows[0]
        assert li.county == county, county
        assert li.listing_type is ListingType.LIS_PENDENS, county
        assert main._in_scope(li) is True, county


def test_true_footprint_county_keeps_foreclosure_sale():
    rows = _rows_for("Buncombe")
    assert len(rows) == 1
    li = rows[0]
    assert li.county == "Buncombe"
    assert li.listing_type is ListingType.FORECLOSURE_SALE
    assert main._in_scope(li) is True


def test_unfixed_type_would_have_been_dropped_for_mecklenburg():
    """Documents the bug directly: a raw FORECLOSURE_SALE for Mecklenburg is
    unreachable regardless of any other field."""
    import copy
    from datetime import datetime, UTC

    from foreclosure_scraper.models import Listing, PropertyKind

    li = Listing(
        source="public_notices.ncnotices",
        source_url="https://example.com/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Mecklenburg",
        street_address="123 Test St",
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        raw={},
    )
    assert main._in_scope(li) is False
    lis = copy.copy(li)
    lis.listing_type = ListingType.LIS_PENDENS
    assert main._in_scope(lis) is True
