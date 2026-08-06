"""COASTAL_COUNTY_BYPASS_SOURCES must beat the provisional oceanfront tag.

THE BUG THIS PINS (found 2026-08-06, cost 450 live leads)
    _in_scope() admits a coastal row by several paths, and the path taken decides
    whether the row SURVIVES publish:

        _coastal_county_source()  -> tags raw.coastal_county      -> kept forever
        _oceanfront_pending()     -> tags raw.oceanfront_pending  -> re-tested at
                                     publish, and DELETED unless it geocodes
                                     within a few hundred metres of the Atlantic

    _oceanfront_pending() matches ANY coastal-county row carrying a street
    address or a parcel_id. So while it was checked first, every bypass-source
    row with either field took the provisional path, and the publish re-pass then
    deleted it for failing a beach test those sources are explicitly exempt from.

    Measured damage on the 2026-08-06 board: Georgetown 408 of 444 deleted
    (leaving ONE), all 23 Horry FLC, 14 Charleston MIE. Georgetown's delinquent
    tax sale IS the product of georgetown_civicengage, so the county read as dead
    while the scraper was fetching it correctly and the pipeline discarded it.

    The failure is invisible without this test: nothing errors, the scraper
    reports success, and the leads simply are not on the board.
"""
from __future__ import annotations

from foreclosure_scraper.main import (
    COASTAL_COUNTY_BYPASS_SOURCES, _in_scope,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _lead(source, county, state="SC", **kw):
    return Listing(
        source=source, source_url="https://example.gov/x",
        listing_type=ListingType.DISTRESSED, property_kind=PropertyKind.UNKNOWN,
        county=county, state=state, raw={}, **kw,
    )


def _tag(li):
    raw = li.raw if isinstance(li.raw, dict) else {}
    for k in ("coastal_county", "oceanfront", "oceanfront_pending",
              "downtown_charleston_pending"):
        if raw.get(k):
            return k
    return None


def test_bypass_source_with_parcel_id_is_unconditional_not_pending():
    """The exact Georgetown shape: bypass source, coastal county, parcel, no coords."""
    li = _lead("counties_sc.georgetown_civicengage", "Georgetown",
               parcel_id="04-0123-456-78-90")
    assert _in_scope(li) is True
    assert _tag(li) == "coastal_county", (
        "a declared bypass source must be admitted unconditionally; "
        "oceanfront_pending here means the publish re-pass will delete it")


def test_bypass_source_with_street_address_is_unconditional_not_pending():
    li = _lead("counties_sc.horry_flc", "Horry", street_address="123 Main St")
    assert _in_scope(li) is True
    assert _tag(li) == "coastal_county"


def test_bypass_source_far_inland_still_survives_the_publish_repass():
    """Conway is ~20 miles inland. A bypass row there must NOT be beach-tested."""
    li = _lead("counties_sc.horry_flc", "Horry", street_address="500 Elm St",
               city="Conway", latitude=33.8360, longitude=-79.0470)
    assert _in_scope(li) is True
    assert _tag(li) != "oceanfront_pending"


def test_non_bypass_source_still_gets_the_provisional_tag():
    """The oceanfront-only policy must keep working for everything else."""
    li = _lead("national.landwatch", "Georgetown", street_address="9 Beach Rd")
    assert _in_scope(li) is True
    assert _tag(li) == "oceanfront_pending"


def test_every_bypass_source_survives_with_a_parcel_id():
    """Not one entry in the list may be shadowed by the provisional path."""
    coastal_for = {"SC": "Charleston", "NC": "Brunswick"}
    shadowed = []
    for src in sorted(COASTAL_COUNTY_BYPASS_SOURCES):
        state = "SC" if ".counties_sc" in f".{src}" else "NC"
        li = _lead(src, coastal_for[state], state=state, parcel_id="123-45-678")
        if not _in_scope(li) or _tag(li) == "oceanfront_pending":
            shadowed.append(src)
    assert not shadowed, f"bypass shadowed by the provisional path: {shadowed}"


def test_genuine_oceanfront_row_is_still_tagged_oceanfront():
    """The strict check runs FIRST, so real beachfront keeps its own tag."""
    li = _lead("counties_sc.horry_flc", "Horry", street_address="1 Ocean Blvd",
               latitude=33.6060, longitude=-78.9670)   # Surfside Beach
    assert _in_scope(li) is True
    assert _tag(li) == "oceanfront"


def test_non_coastal_county_is_unaffected_by_the_bypass():
    """A bypass source pointed at a non-coastal denied county must not sneak in."""
    li = _lead("counties_sc.horry_flc", "Greenville", parcel_id="1")
    assert _in_scope(li) is False
