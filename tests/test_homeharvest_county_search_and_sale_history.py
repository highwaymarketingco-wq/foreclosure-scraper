"""national.homeharvest (homeharvest.py) -- HERMES extraction-completeness
audit, batch 17 (2026-10-04). This scraper had NO dedicated test file before
this batch despite being a production source.

Two real gaps found and fixed, both live-verified:

1. SEARCH-STRING UNDER-COVERAGE. `_scrape_one_county` searched Realtor.com
   by SEAT-TOWN CITY NAME ("Rutherfordton, NC") instead of the whole county.
   This is the same root-cause class the sibling national.distressed
   scraper found and fixed 2026-10-03 (there it was a scope-widening fix
   across the county SET; here the 18-county footprint itself is correct --
   these are flip-type listings, correctly scoped -- the bug is the search
   STRING missing most of each county's area). Live-verified: Rutherfordton,
   NC (seat) -> 0 rows vs "Rutherford County, NC" -> 1 (a Mooresboro
   listing, a different town than the seat); Spartanburg, SC (seat) -> 3
   rows vs "Spartanburg County, SC" -> 8 (nearly 3x -- Boiling Springs/
   Pauline/Wellford listings the seat-only search never saw). A full live
   18-county comparison run this batch: 28 raw rows (seat-only) -> 47
   (county-wide), +68%.

2. last_sold_price / last_sold_date / sold_price / hoa_fee / stories /
   new_construction were already present on HomeHarvest's own dataframe row
   (zero extra requests) but never read. last_sold_price/date are a real
   distress signal -- live-sampled 8 current SC foreclosure-flagged rows,
   6/8 carry a recent prior sale price/date (e.g. a real current row last
   sold for $20,000 in 2023, now back on the market as a foreclosure).
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.homeharvest import _scrape_one_county, _to_listing


def _row(**overrides) -> dict:
    base = {
        "property_url": "https://www.realtor.com/x/1",
        "status": "FOR_SALE",
        "mls_status": "Active",
        "style": "single_family",
        "street": "131 Case Ave",
        "city": "Spartanburg",
        "state": "SC",
        "zip_code": "29301",
        "list_price": 45000,
        "last_sold_price": 20000,
        "last_sold_date": "2023-02-27 00:00:00",
        "sold_price": 20000,
        "hoa_fee": 0,
        "stories": 1,
        "new_construction": False,
    }
    base.update(overrides)
    return base


def test_scrape_one_county_searches_whole_county_not_seat_town(monkeypatch):
    """Regression pin for fix #1: the location string passed to HomeHarvest
    must be the "<County> County, <ST>" form, not "<seat>, <ST>"."""
    captured_locations = []

    class _FakeHomeHarvest:
        @staticmethod
        def scrape_property(location, listing_type, foreclosure, past_days=None):
            captured_locations.append(location)
            return None

    import sys
    sys.modules["homeharvest"] = _FakeHomeHarvest()
    try:
        _scrape_one_county("Rutherfordton", "NC", "Rutherford")
    finally:
        del sys.modules["homeharvest"]

    assert captured_locations, "scrape_property was never called"
    for loc in captured_locations:
        assert loc == "Rutherford County, NC", (
            f"expected whole-county search string, got {loc!r} "
            "(seat-town search under-covers the county -- see module docstring)"
        )
        assert "Rutherfordton" not in loc


def test_captures_last_sold_price_and_date():
    li = _to_listing(_row())
    assert li is not None
    assert li.raw["homeharvest"]["last_sold_price"] == 20000.0
    assert li.raw["homeharvest"]["last_sold_date"] == "2023-02-27 00:00:00"
    assert li.raw["homeharvest"]["sold_price"] == 20000.0


def test_captures_hoa_fee_and_stories():
    li = _to_listing(_row(hoa_fee=250, stories=2))
    assert li.raw["homeharvest"]["hoa_fee"] == 250.0
    assert li.raw["homeharvest"]["stories"] == 2.0


def test_missing_sale_history_is_none_not_crash():
    li = _to_listing(_row(last_sold_price=None, last_sold_date=None, sold_price=None))
    assert li.raw["homeharvest"]["last_sold_price"] is None
    assert li.raw["homeharvest"]["last_sold_date"] is None


def test_new_construction_boolean_roundtrips():
    li = _to_listing(_row(new_construction=True))
    assert li.raw["homeharvest"]["new_construction"] is True
