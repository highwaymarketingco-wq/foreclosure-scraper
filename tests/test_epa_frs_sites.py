"""EPA brownfield + Superfund sites via FRS.

A brownfield or Superfund listing is a recorded environmental encumbrance on a
parcel — it suppresses value, complicates financing, and is often why a property
has sat unsold for years. Both states in one query, which is what the thin
counties need.
"""
from __future__ import annotations

import foreclosure_scraper.scrapers.counties_generic.epa_frs_sites as E


def _row(county="BUNCOMBE", addr="9 REED STREET", name="GLEN ROCK HOTEL"):
    return {"county_name": county, "location_address": addr,
            "primary_name": name, "city_name": "ASHEVILLE",
            "pgm_sys_id": "NCD986178141"}


def test_out_of_footprint_counties_are_dropped():
    """FRS has no county parameter, so filtering happens here. ROBESON is a real
    NC county in the feed and must not reach the board."""
    assert E._to_listing(_row(county="ROBESON"), "NC", "ACRES") is None
    assert E._to_listing(_row(county="MECKLENBURG"), "NC", "SEMS") is None


def test_county_case_is_normalised_to_canonical_spelling():
    """FRS returns uppercase. 'MCDOWELL'.title() gives 'Mcdowell', which does not
    match 'McDowell' in the scope filter or any downstream join."""
    li = E._to_listing(_row(county="MCDOWELL"), "NC", "ACRES")
    assert li.county == "McDowell"
    assert E._to_listing(_row(county="buncombe"), "NC", "ACRES").county == "Buncombe"


def test_a_row_without_an_address_is_dropped():
    assert E._to_listing(_row(addr=""), "NC", "ACRES") is None
    assert E._to_listing(_row(addr="  "), "NC", "ACRES") is None


def test_placeholder_values_are_not_treated_as_data():
    for junk in ("NA", "N/A", "none", "NULL", "unknown", ""):
        assert E._clean(junk) is None


def test_each_program_gets_its_own_process_tag():
    a = E._to_listing(_row(), "NC", "ACRES")
    s = E._to_listing(_row(), "NC", "SEMS")
    assert a.foreclosure_process == "brownfield"
    assert s.foreclosure_process == "superfund"
    assert a.source != s.source


def test_both_states_are_covered_and_footprint_is_complete():
    assert len(E.FOOTPRINT["NC"]) == 11
    assert len(E.FOOTPRINT["SC"]) == 7
    assert "UNION" in E.FOOTPRINT["SC"] and "MITCHELL" in E.FOOTPRINT["NC"]


def test_read_through_frs_not_the_broken_sems_endpoint():
    """sems.envirofacts_site returns HTTP 500 for both states (checked
    2026-08-06). FRS carries the same programs and answers 200."""
    assert "frs.frs_program_facility" in E.FRS
    assert "sems.envirofacts_site" not in open(E.__file__).read().split('"""', 2)[2]


def test_row_maps_to_a_usable_lead():
    li = E._to_listing(_row(), "NC", "ACRES")
    assert li.state == "NC" and li.county == "Buncombe"
    assert li.street_address == "9 REED STREET"
    assert li.owner_name == "GLEN ROCK HOTEL"
    assert li.raw["epa_frs"]["program"] == "ACRES"
