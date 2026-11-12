"""national.fannie_homepath: 2026-10-03 per-column audit for lt_reo.

Fannie's own `county` field is blank on a real chunk of rows -- confirmed live
against the board, 67/857 NC+SC rows (7.8%) had no county at all despite a
real city/zip/geoPoint, e.g. "94 Crestview Heights, Franklin, NC 28734" (Macon
County) and "45 Sugar Cove Road, Weaverville, NC" (Buncombe County, one of the
18 footprint counties). This is the same bug class zillow_foreclosures.py
already found and fixed (2026-10-01 national/reo audit,
tests/test_zillow_county_fallback.py): REO is a "flip" listing type
(main._FLIP_LISTING_TYPES), which gates on the NARROW in_scope(county, state)
check, and in_scope(None, state) is unconditionally False -- so a blank county
silently drops a real in-footprint lead at the scope gate.

Fixed by falling back to upstate_county_for (the WNC/upstate-SC gazetteer
zillow_foreclosures.py / crexi_multifamily.py / estate_sales.py already use
for this exact problem), then bankruptcy_county_for (the full 146-county
gazetteer, since Fannie's own bboxes are genuinely statewide rather than
footprint-only), then coastal_county_for for parity with
zillow_foreclosures.py's fallback chain.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national import fannie_homepath as m


def _prop(city: str, state: str = "NC", county: str | None = None, uuid: str = "abc-1") -> dict:
    return {
        "propertyUuid": uuid,
        "addressLine1": "1 Test St",
        "city": city,
        "state": state,
        "zipCode": "28801",
        "county": county,
        "propertyType": "Single Family",
        "price": 100000,
    }


def test_blank_county_resolves_via_upstate_gazetteer():
    """Weaverville NC is one of the 18 footprint counties (Buncombe) and sits
    in the upstate/WNC gazetteer already relied on elsewhere in this codebase."""
    li = m._to_listing(_prop("Weaverville", county=None), m.FannieHomePath.slug)
    assert li is not None
    assert li.county == "Buncombe"


def test_blank_county_resolves_via_statewide_bankruptcy_gazetteer():
    """Franklin NC (Macon County's seat) is outside the 18-county footprint and
    outside the narrower upstate gazetteer, but IS in the full 146-county
    bankruptcy-caption gazetteer -- live-confirmed the single biggest chunk
    (25/67) of blank-county fannie_homepath rows on the real board."""
    li = m._to_listing(_prop("Franklin", county=None), m.FannieHomePath.slug)
    assert li is not None
    assert li.county == "Macon"


def test_blank_county_with_no_gazetteer_match_stays_none():
    """A genuinely unresolvable city must not get a fabricated county -- the
    fix must not over-admit."""
    li = m._to_listing(_prop("Nowhereville", county=None), m.FannieHomePath.slug)
    assert li is not None
    assert li.county is None


def test_explicit_api_county_still_wins_over_the_gazetteer():
    li = m._to_listing(_prop("Weaverville", county="MECKLENBURG COUNTY"), m.FannieHomePath.slug)
    assert li is not None
    assert li.county == "Mecklenburg"
