"""public_notices.nc_notices_counties — selective scope-gate fix.

FOUND 2026-10-04 (HERMES extraction-completeness audit, public_notices
batch): FOOTPRINT deliberately spans 20 NC counties: the 11 real
18-county-footprint counties (Buncombe/Henderson/Gaston/Cleveland/
Rutherford/Burke/Lincoln/McDowell/Polk/Transylvania/Mitchell) PLUS 9 added
purely for distress-signal coverage (Haywood, added 2026-09-30, and 8
coastal counties -- Currituck/Dare/Hyde/Carteret/Onslow/Pender/New Hanover/
Brunswick -- added 2026-08-12). All 9 of those are either explicitly in
config.SCOPE_DENY_COUNTIES or simply outside config.NC_COUNTIES (or both).

ListingType.FORECLOSURE_SALE is a "flip" type gated to the narrow
18-county footprint by main._flip_outside_footprint(), checked before every
other admission path, and this source is not in
main.COASTAL_COUNTY_BYPASS_SOURCES (which excludes flip rows from its
bypass anyway). So every genuinely-scheduled substitute-trustee sale
notice this scraper ever classified FORECLOSURE_SALE for one of those 9
counties was silently dropped at the board gate -- confirmed directly on
the real Haywood fixture test_nc_notices_counties.py already carried
(notice_id 982438, live-captured 2026-09-30): that test asserted
FORECLOSURE_SALE without ever checking main._in_scope(), so the "real
coverage" it was celebrating was half-dropped the whole time.

Fixed by remapping FORECLOSURE_SALE -> LIS_PENDENS in _to_listing() ONLY
when the resolved county is outside the true 18-county footprint -- the 11
real footprint counties keep their flip classification unchanged.
"""
from __future__ import annotations

from foreclosure_scraper import main
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.public_notices import nc_notices_counties as M

_SLUG = "public_notices.nc_notices_counties"

_SALE_TEXT_TEMPLATE = (
    "NORTH CAROLINA {county} COUNTY UNDER AND BY VIRTUE of the power of sale "
    "contained in that certain Deed of Trust executed by John Q. Sample to ABC "
    "Trustee, dated June 1, 2020, default having been made, the undersigned "
    "Substitute Trustee will offer for sale at public auction to the highest "
    "bidder for cash at the courthouse door. The sale will be held on "
    "November 15, 2026 at 10:00 AM."
)


def _row(county: str) -> dict:
    return {
        "notice_id": f"test-{county}",
        "publication": "Test Paper",
        "date_text": "November 1, 2026",
        "published_at": None,
        "county_meta": county,
        "city_meta": "",
        "text": _SALE_TEXT_TEMPLATE.format(county=county.upper()),
    }


def test_true_footprint_county_keeps_foreclosure_sale():
    li = M._to_listing(_row("Buncombe"), _SLUG)
    assert li is not None
    assert li.listing_type is ListingType.FORECLOSURE_SALE
    assert main._in_scope(li) is True


def test_coastal_county_is_remapped_and_reaches_the_board():
    for county in ("Brunswick", "Carteret", "Dare", "New Hanover", "Pender",
                   "Onslow", "Hyde", "Currituck"):
        li = M._to_listing(_row(county), _SLUG)
        assert li is not None, county
        assert li.listing_type is ListingType.LIS_PENDENS, county
        assert main._in_scope(li) is True, county


def test_haywood_is_remapped_and_reaches_the_board():
    li = M._to_listing(_row("Haywood"), _SLUG)
    assert li is not None
    assert li.listing_type is ListingType.LIS_PENDENS
    assert main._in_scope(li) is True


def test_unfixed_type_would_have_been_dropped_for_a_coastal_county():
    """Documents the bug directly: a raw FORECLOSURE_SALE for Brunswick is
    unreachable regardless of any other field. (Since 2026-10-06 the one exception is a point
    within a 5 minute drive of the beach, so the control carries an inland point.)"""
    import copy
    from datetime import datetime, UTC

    from foreclosure_scraper.models import Listing, PropertyKind

    li = Listing(
        source=_SLUG,
        source_url="https://example.com/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Brunswick",
        street_address="123 Test St",
        latitude=34.06,
        longitude=-78.23,
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        raw={},
    )
    assert main._in_scope(li) is False
    lis = copy.copy(li)
    lis.listing_type = ListingType.LIS_PENDENS
    assert main._in_scope(lis) is True


def test_all_20_footprint_counties_are_classified_correctly():
    """Every FOOTPRINT entry either keeps FORECLOSURE_SALE (if truly in the
    18-county footprint) or gets remapped (if not) -- no silent drop either
    way."""
    for county in M.FOOTPRINT:
        li = M._to_listing(_row(county), _SLUG)
        assert li is not None, county
        assert main._in_scope(li) is True, county
        if county in M._FLIP_FOOTPRINT_NAMES:
            assert li.listing_type is ListingType.FORECLOSURE_SALE, county
        else:
            assert li.listing_type is ListingType.LIS_PENDENS, county
