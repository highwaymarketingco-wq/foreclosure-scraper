"""reo.usda_rd: 2026-10-04 final-batch extraction-completeness audit.

This scraper's search table never carried a sale_date anywhere -- the real
foreclosure sale date/time/location only exist on each property's own
PropertyDetail page, which this scraper never fetched. That page also
carries house facts (style/rooms/basement/garage/foundation/heating/
cooling/water/sewage), an annual tax bill $, lot size, an approximate
year-built (from an "Age:" field), a Govt Bid cross-check, and a full photo
gallery. ``REAL_DETAIL_HTML`` below is a trimmed-but-real capture
(2026-10-04, resales.usda.gov SFHPropertyDetail?id=7619, a real current
Lexington County SC listing).
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from foreclosure_scraper.scrapers.reo import usda_rd as M

REAL_DETAIL_HTML = """
<html><body>
<div class="col-md-4 text-left">House Style:</div><div class="col-md-8 text-left">-Brick</div><br>
<div class="col-md-4 text-left">Beds:</div><div class="col-md-8 text-left">3</div><br>
<div class="col-md-4 text-left">Baths:</div><div class="col-md-8 text-left">2</div><br>
<div class="col-md-4 text-left">Rooms:</div><div class="col-md-8 text-left">5</div><br>
<div class="col-md-4 text-left">Living Area:</div><div class="col-md-8 text-left">1,260</div><br>
<div class="col-md-4 text-left">Basement:</div><div class="col-md-8 text-left">Crawlspace</div><br>
<div class="col-md-4 text-left">Garage:</div><div class="col-md-8 text-left">N/A</div><br>
<div class="col-md-4 text-left">Foundation:</div><div class="col-md-8 text-left">Block</div><br>
<div class="col-md-4 text-left">Age:</div><div class="col-md-8 text-left">27</div><br>
<div class="col-md-4 text-left">Heating:</div><div class="col-md-8 text-left">Forced Air</div><br>
<div class="col-md-4 text-left">Cooling:</div><div class="col-md-8 text-left">Central Air</div><br>
<div class="col-md-4 text-left">Water:</div><div class="col-md-8 text-left">Community</div><br>
<div class="col-md-4 text-left">Sewage:</div><div class="col-md-8 text-left">Septic</div><br>
<div class="col-md-4 text-left">Lot Size:</div><div class="col-md-8 text-left"></div><br>
<div class="col-md-4 text-left">Real Estate Taxes:</div><div class="col-md-8 text-left">$517</div><br>
<div class="interior-heading">Foreclosure Sale Information</div>
<div class="col-md-4 text-left">Location:</div><div class="col-md-8 text-left">Lexington County Judicial Complex 205 East Main St</div><br>
<div class="col-md-4 text-left"></div><div class="col-md-8 text-left">Lexington, South Carolina</div><br>
<div class="col-md-4 text-left">Sale Date:</div><div class="col-md-8 text-left">5-5-25</div><br>
<div class="col-md-4 text-left">Sale Time:</div><div class="col-md-8 text-left">11:00 am</div><br>
<div class="col-md-4 text-left">Govt Bid:</div><div class="col-md-8 text-left">$166,191</div><br>
<ul class="propertyimages">
<li><img src="https://www.resales.usda.gov:443/SFH_INTRANET/1745439934108-1.png" class="altImage"></li>
<li><img src="https://www.resales.usda.gov:443/SFH_INTRANET/1745439934108-2.png" class="altImage"></li>
</ul>
</body></html>
"""

# A real-shaped acreage listing (lot size present, different units).
REAL_DETAIL_HTML_WITH_LOT = REAL_DETAIL_HTML.replace(
    '<div class="col-md-4 text-left">Lot Size:</div><div class="col-md-8 text-left"></div><br>',
    '<div class="col-md-4 text-left">Lot Size:</div><div class="col-md-8 text-left">0.75 Acres</div><br>',
)


def test_parse_detail_page_extracts_sale_info_and_house_facts():
    out = M._parse_detail_page(REAL_DETAIL_HTML)
    assert out["sale_date_text"] == "5-5-25"
    assert out["sale_time_text"] == "11:00 am"
    assert out["sale_location"] == (
        "Lexington County Judicial Complex 205 East Main St, "
        "Lexington, South Carolina"
    )
    assert out["govt_bid_text"] == "$166,191"
    assert out["house_style"] == "-Brick"
    assert out["rooms"] == "5"
    assert out["basement"] == "Crawlspace"
    assert out["garage"] == "N/A"
    assert out["foundation"] == "Block"
    assert out["heating"] == "Forced Air"
    assert out["cooling"] == "Central Air"
    assert out["water"] == "Community"
    assert out["sewage"] == "Septic"
    assert out["age_text"] == "27"
    assert out["annual_tax_text"] == "$517"
    assert out["gallery"] == [
        "https://www.resales.usda.gov:443/SFH_INTRANET/1745439934108-1.png",
        "https://www.resales.usda.gov:443/SFH_INTRANET/1745439934108-2.png",
    ]
    assert "lot_size_text" not in out  # blank on this real listing


def test_parse_lot_size_sqft_acres_and_sqft_units():
    assert M._parse_lot_size_sqft("0.75 Acres") == 0.75 * 43560.0
    assert M._parse_lot_size_sqft("32,670 sq ft") == 32670.0
    assert M._parse_lot_size_sqft(None) is None
    assert M._parse_lot_size_sqft("Unknown") is None  # no recognized unit -> never guess


def _make_listing() -> "M.Listing":
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind
    return Listing(
        source="reo.usda_rd", source_url="https://x/SFHPropertyDetail?id=7619",
        listing_type=ListingType.REO, property_kind=PropertyKind.SINGLE_FAMILY,
        state="SC", street_address="341 Crestwood Arch", city="Lexington",
        county="Lexington", zip_code="29073", opening_bid=166191.0,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={"usda_rd": {"kind": "SFH"}},
    )


def test_enrich_from_detail_fills_sale_date_above_all():
    """The headline fix: sale_date was NEVER populated anywhere before this."""
    resp = MagicMock(status_code=200, text=REAL_DETAIL_HTML)
    c = AsyncMock()
    c.get = AsyncMock(return_value=resp)
    li = _make_listing()
    asyncio.run(M._enrich_from_detail(c, li, "https://x/SFHPropertyDetail?id=7619"))
    assert li.sale_date == datetime(2025, 5, 5)


def test_enrich_from_detail_fills_year_built_from_age():
    resp = MagicMock(status_code=200, text=REAL_DETAIL_HTML)
    c = AsyncMock()
    c.get = AsyncMock(return_value=resp)
    li = _make_listing()
    asyncio.run(M._enrich_from_detail(c, li, "https://x/SFHPropertyDetail?id=7619"))
    expected_year = datetime.utcnow().year - 27
    assert li.year_built == expected_year


def test_enrich_from_detail_fills_lot_size_and_extends_gallery():
    resp = MagicMock(status_code=200, text=REAL_DETAIL_HTML_WITH_LOT)
    c = AsyncMock()
    c.get = AsyncMock(return_value=resp)
    li = _make_listing()
    li.raw["images"] = {"real": ["https://x/table-thumb.png"]}
    asyncio.run(M._enrich_from_detail(c, li, "https://x/SFHPropertyDetail?id=7619"))
    assert li.lot_size_sqft == 0.75 * 43560.0
    assert li.raw["images"]["real"] == [
        "https://x/table-thumb.png",
        "https://www.resales.usda.gov:443/SFH_INTRANET/1745439934108-1.png",
        "https://www.resales.usda.gov:443/SFH_INTRANET/1745439934108-2.png",
    ]


def test_enrich_from_detail_records_house_facts_and_tax_under_raw():
    resp = MagicMock(status_code=200, text=REAL_DETAIL_HTML)
    c = AsyncMock()
    c.get = AsyncMock(return_value=resp)
    li = _make_listing()
    asyncio.run(M._enrich_from_detail(c, li, "https://x/SFHPropertyDetail?id=7619"))
    detail = li.raw["usda_rd"]["detail"]
    assert detail["house_style"] == "-Brick"
    assert detail["basement"] == "Crawlspace"
    assert detail["sale_location"].startswith("Lexington County Judicial Complex")
    assert detail["annual_tax"] == 517.0
    # tax_value (an ASSESSED-value field other scrapers use) must NOT be
    # touched by an annual tax BILL figure -- different semantics.
    assert li.tax_value is None


def test_enrich_from_detail_never_raises_on_fetch_failure():
    c = AsyncMock()
    c.get = AsyncMock(side_effect=OSError("connection reset"))
    li = _make_listing()
    asyncio.run(M._enrich_from_detail(c, li, "https://x/SFHPropertyDetail?id=7619"))
    assert li.sale_date is None  # untouched, not crashed


def test_search_county_wires_detail_fetch_when_budget_available():
    """End-to-end _search_county(): a real id=7619-shaped row gets its
    detail page fetched and sale_date filled when a budget is supplied."""
    from tests.test_usda_rd_photo import _REAL_TABLE_HTML

    calls = []

    async def post(*a, **kw):
        return MagicMock(status_code=200, text=_REAL_TABLE_HTML)

    async def get(url, **kw):
        calls.append(url)
        return MagicMock(status_code=200, text=REAL_DETAIL_HTML)

    c = AsyncMock()
    c.post = post
    c.get = get

    budget = [5]
    out = asyncio.run(M._search_county(c, "SC", "SFH", "063", detail_budget=budget))
    assert len(out) == 1
    assert out[0].sale_date == datetime(2025, 5, 5)
    assert budget[0] == 4  # decremented by exactly one real fetch
    assert len(calls) == 1


def test_search_county_skips_detail_fetch_when_budget_is_none():
    """Backward-compat: no detail_budget argument at all (as the existing
    test_usda_rd_photo.py fixtures call it) -> zero detail GETs, unchanged
    pre-fix behavior."""
    from tests.test_usda_rd_photo import _REAL_TABLE_HTML

    async def post(*a, **kw):
        return MagicMock(status_code=200, text=_REAL_TABLE_HTML)

    c = AsyncMock()
    c.post = post
    c.get = AsyncMock(side_effect=AssertionError("must not be called"))

    out = asyncio.run(M._search_county(c, "SC", "SFH", "063"))
    assert len(out) == 1
    assert out[0].sale_date is None


def test_search_county_respects_an_exhausted_budget():
    from tests.test_usda_rd_photo import _REAL_TABLE_HTML

    async def post(*a, **kw):
        return MagicMock(status_code=200, text=_REAL_TABLE_HTML)

    c = AsyncMock()
    c.post = post
    c.get = AsyncMock(side_effect=AssertionError("must not be called"))

    budget = [0]
    out = asyncio.run(M._search_county(c, "SC", "SFH", "063", detail_budget=budget))
    assert len(out) == 1
    assert out[0].sale_date is None
    assert budget[0] == 0
