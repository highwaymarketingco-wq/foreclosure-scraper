"""national.courtlistener_bankruptcy county-attribution gazetteer widening.

docs/coverage_gap_build_plan_2026-09-23.md item 3: the 4 federal bankruptcy
districts covering NC+SC (ncwb/ncmb/nceb/scb) already partition the entirety
of both states -- every county's dockets were already being fetched every
run -- but county attribution from a city keyword in the case caption was
done via a hardcoded 21-county/~28-town CITY_TO_COUNTY dict
(courtlistener_bankruptcy.py lines ~104-129 before this change), so filings
whose caption mentioned a city outside that list fell back to a state-level,
county-less lead.

This is purely an attribution-gazetteer fix -- no live network call was
needed to verify it (unlike items 1/2, which needed to confirm a live
endpoint's behavior): CourtListener's docket/case-name shape is already
covered by existing tests (test_courtlistener_search_lane.py,
test_courtlistener_dedup.py), and the fix itself is a pure city->county
lookup table built from NC/SC geography, cross-checked against the two
existing gazetteers already in this codebase (_upstate_city_to_county.py,
_coastal_city_to_county.py) for consistency where they overlap. See
`_bankruptcy_city_to_county.py`'s module docstring for why those two
existing gazetteers were NOT imported/merged wholesale (key-shape mismatch,
differing curation intent, and one confirmed collision: the upstate
gazetteer self-maps "Henderson" -> Henderson County for ITS purposes, but
the actual town of Henderson, NC is Vance County's seat).

A second, latent bug is fixed alongside the widening: the old
`_county_from_text` returned its OWN hardcoded state per matched keyword,
so a same-named town in the other state (the dict actually had "CLINTON":
("SC", "Laurens") even though Clinton, NC is a real town in Sampson County)
could silently flip an NC-filed docket's state to SC. Since a docket's
state is always known up front (the court it was filed in), the fixed
version takes that state as an input and only ever recovers the COUNTY
within it -- it can no longer override state.
"""
from __future__ import annotations

from foreclosure_scraper._bankruptcy_city_to_county import (
    KNOWN_CITIES,
    bankruptcy_county_for,
)
from foreclosure_scraper.scrapers.national.courtlistener_bankruptcy import (
    COURT_STATE,
    _county_from_text,
)
from foreclosure_scraper.validation import NC_COUNTIES, SC_COUNTIES


def test_gazetteer_covers_all_146_counties():
    covered_nc = {bankruptcy_county_for(c, "NC") for c in KNOWN_CITIES}
    covered_nc.discard(None)
    covered_sc = {bankruptcy_county_for(c, "SC") for c in KNOWN_CITIES}
    covered_sc.discard(None)
    missing_nc = set(NC_COUNTIES) - covered_nc
    missing_sc = set(SC_COUNTIES) - covered_sc
    assert not missing_nc, f"NC counties with no gazetteer entry: {sorted(missing_nc)}"
    assert not missing_sc, f"SC counties with no gazetteer entry: {sorted(missing_sc)}"


def test_gazetteer_has_no_typo_counties():
    """Every county name the gazetteer emits must be a real, canonical
    NC/SC county name -- a typo here would silently misattribute filings
    to a county that fails the scope gate and gets dropped."""
    for city in KNOWN_CITIES:
        for state, valid in (("NC", NC_COUNTIES), ("SC", SC_COUNTIES)):
            county = bankruptcy_county_for(city, state)
            if county is not None:
                assert county in valid, (
                    f"{city!r}/{state} maps to {county!r}, not a real county"
                )


def test_previously_uncovered_counties_now_resolve():
    """Spot-check counties the old 21-county dict had no entry for at all --
    these previously fell through to a state-only, county-less lead."""
    for city, county, state in [
        ("Raleigh", "Wake", "NC"),
        ("Greensboro", "Guilford", "NC"),
        ("Winston-Salem", "Forsyth", "NC"),
        ("Wilmington", "New Hanover", "NC"),
        ("Fayetteville", "Cumberland", "NC"),
        ("Columbia", "Richland", "SC"),
        ("Conway", "Horry", "SC"),
        ("Sumter", "Sumter", "SC"),
        ("Rock Hill", "York", "SC"),
    ]:
        assert bankruptcy_county_for(city, state) == county, (
            f"{city}/{state} should resolve to {county}"
        )


def test_cross_state_and_cross_county_collisions_resolved_by_state():
    """These city names name a DIFFERENT county depending on state (or, for
    same-state pairs, a different county than a same-named place elsewhere
    in the state) -- the exact class of bug the coverage-gap plan flagged
    ("check how _upstate_city_to_county.py's upstate_county_for(city, state)
    signature handles this and mirror that safety")."""
    assert bankruptcy_county_for("Camden", "NC") == "Camden"     # a whole NC county
    assert bankruptcy_county_for("Camden", "SC") == "Kershaw"    # Kershaw's seat
    assert bankruptcy_county_for("Columbia", "NC") == "Tyrrell"  # tiny NC town
    assert bankruptcy_county_for("Columbia", "SC") == "Richland"  # SC capital
    assert bankruptcy_county_for("Greenville", "NC") == "Pitt"
    assert bankruptcy_county_for("Greenville", "SC") == "Greenville"
    assert bankruptcy_county_for("Clinton", "NC") == "Sampson"
    assert bankruptcy_county_for("Clinton", "SC") == "Laurens"
    assert bankruptcy_county_for("Lexington", "NC") == "Davidson"
    assert bankruptcy_county_for("Lexington", "SC") == "Lexington"
    assert bankruptcy_county_for("Williamston", "NC") == "Martin"
    assert bankruptcy_county_for("Williamston", "SC") == "Anderson"  # a real,
                                                                       # different
                                                                       # Anderson Co
                                                                       # SC town
    assert bankruptcy_county_for("Marion", "NC") == "McDowell"
    assert bankruptcy_county_for("Marion", "SC") == "Marion"


def test_henderson_resolves_to_vance_not_henderson_county():
    """The specific collision flagged in _bankruptcy_city_to_county.py's
    module docstring: Henderson, NC is Vance County's seat, NOT a town in
    Henderson County (whose seat is the differently-named Hendersonville).
    A naive reuse of _upstate_city_to_county.py's self-referential
    "Henderson" -> Henderson County entry would have gotten this wrong."""
    assert bankruptcy_county_for("Henderson", "NC") == "Vance"
    assert bankruptcy_county_for("Hendersonville", "NC") == "Henderson"


def test_split_or_ambiguous_cities_deliberately_unmapped():
    """Cities whose real-world footprint genuinely straddles county lines
    are left unmapped rather than asserting an unverified single-county
    guess -- Hickory (Catawba/Burke/Alexander/Caldwell), Rocky Mount
    (Nash/Edgecombe), Summerville and Goose Creek (Berkeley/Charleston/
    Dorchester)."""
    assert bankruptcy_county_for("Hickory", "NC") is None
    assert bankruptcy_county_for("Rocky Mount", "NC") is None
    assert bankruptcy_county_for("Summerville", "SC") is None
    assert bankruptcy_county_for("Goose Creek", "SC") is None


def test_county_from_text_never_overrides_the_courts_state():
    """The fixed bug: a docket filed in an NC district must stay NC even if
    the case name happens to contain a town name that also exists (under a
    different county) in SC, and vice versa. This function no longer
    returns a state at all -- it takes the court-derived state as an input."""
    # "Clinton" alone, queried under NC, must resolve within NC (Sampson),
    # not silently jump state to SC's Clinton (Laurens).
    assert _county_from_text("IN RE: Jane Doe of Clinton", "NC") == "Sampson"
    assert _county_from_text("IN RE: John Roe of Clinton", "SC") == "Laurens"
    assert _county_from_text("IN RE: A Debtor of Camden", "NC") == "Camden"
    assert _county_from_text("IN RE: A Debtor of Camden", "SC") == "Kershaw"


def test_county_from_text_returns_none_not_a_tuple():
    """Signature changed from `(state, county)` tuple to plain `county | None`
    -- state is a required input now, not an inferred output. Every caller
    (courtlistener_bankruptcy, courtlistener_civil, courtlistener_adversary)
    was updated; this pins the new contract so a future revert is caught."""
    result = _county_from_text("no city mentioned anywhere", "NC")
    assert result is None
    result2 = _county_from_text("IN RE: Bob of Charlotte", "NC")
    assert result2 == "Mecklenburg"
    assert not isinstance(result2, tuple)


def test_court_state_map_unchanged():
    """The 4-district state mapping itself didn't change -- only how county
    is recovered within that state."""
    assert COURT_STATE == {"ncwb": "NC", "ncmb": "NC", "nceb": "NC", "scb": "SC"}


def test_bankruptcy_county_for_requires_both_city_and_state():
    assert bankruptcy_county_for(None, "NC") is None
    assert bankruptcy_county_for("Charlotte", None) is None
    assert bankruptcy_county_for("", "NC") is None
