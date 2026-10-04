"""EPA brownfield + Superfund sites via FRS.

A brownfield or Superfund listing is a recorded environmental encumbrance on a
parcel — it suppresses value, complicates financing, and is often why a property
has sat unsold for years. Both states in one query, which is what the thin
counties need.

FOOTPRINT was widened 2026-10-03 from the 18-county (11 NC + 7 SC) flip
footprint to every real NC/SC county -- the fetch already pulled the full
statewide result either way, so the old dict was discarding real rows for
zero fetch-cost savings. Same bug class as the 2026-10-03 comps fix.
"""
from __future__ import annotations

import foreclosure_scraper.scrapers.counties_generic.epa_frs_sites as E


def _row(county="BUNCOMBE", addr="9 REED STREET", name="GLEN ROCK HOTEL", registry_id="110038733109"):
    return {"county_name": county, "location_address": addr,
            "primary_name": name, "city_name": "ASHEVILLE",
            "pgm_sys_id": "NCD986178141", "registry_id": registry_id}


def test_real_nc_sc_counties_outside_the_old_footprint_are_kept():
    """2026-10-03 fix: ROBESON and MECKLENBURG are real NC counties that FRS
    already returns in the single statewide fetch -- the old FOOTPRINT dict
    discarded them for no fetch-cost reason. They must now reach the board,
    same as any other real NC/SC county."""
    li = E._to_listing(_row(county="ROBESON"), "NC", "ACRES")
    assert li is not None and li.county == "Robeson"
    li2 = E._to_listing(_row(county="MECKLENBURG"), "NC", "SEMS")
    assert li2 is not None and li2.county == "Mecklenburg"


def test_garbage_county_values_still_drop():
    """FRS's county_name occasionally carries a data-entry typo (verified live
    2026-10-03: 'BURTCOMBE', 'ALLLENDALE') that matches no real county name --
    those rows still correctly drop, same as before the widen."""
    assert E._to_listing(_row(county="BURTCOMBE"), "NC", "ACRES") is None
    assert E._to_listing(_row(county="NOT A REAL COUNTY"), "NC", "ACRES") is None


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


def test_both_states_are_covered_statewide():
    """Widened 2026-10-03 from the 18-county (11 NC + 7 SC) flip footprint to
    every real NC/SC county (validation.py)."""
    from foreclosure_scraper.validation import NC_COUNTIES, SC_COUNTIES
    assert len(E.FOOTPRINT["NC"]) == 100 == len(NC_COUNTIES)
    assert len(E.FOOTPRINT["SC"]) == 46 == len(SC_COUNTIES)
    assert "UNION" in E.FOOTPRINT["SC"] and "MITCHELL" in E.FOOTPRINT["NC"]
    assert "GREENVILLE" in E.FOOTPRINT["SC"] and "MECKLENBURG" in E.FOOTPRINT["NC"]


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


def test_registry_id_builds_a_per_facility_detail_link():
    """Every row used to ship the same generic 'https://www.epa.gov/frs'
    source_url no matter which facility it was. registry_id is FRS's own
    cross-program key and resolves to a real per-facility detail page
    (verified live 2026-10-01, HTTP 200, no auth) -- use it."""
    li = E._to_listing(_row(registry_id="110038733109"), "NC", "ACRES")
    assert li.raw["epa_frs"]["registry_id"] == "110038733109"
    assert li.source_url == (
        "https://ofmpub.epa.gov/frs_public2/fii_query_dtl.disp_program_facility"
        "?p_registry_id=110038733109"
    )


def test_missing_registry_id_falls_back_to_generic_url():
    li = E._to_listing(_row(registry_id=None), "NC", "ACRES")
    assert li.raw["epa_frs"]["registry_id"] is None
    assert li.source_url == "https://www.epa.gov/frs"


def test_supplemental_location_is_captured_when_present():
    """EXTRACTION-COMPLETENESS 2026-10-03: live field-population survey of
    all 3,809 current NC+SC ACRES/SEMS rows found supplemental_location
    populated on 14 (0.4%) carrying real content no other field has --
    live example: 'PIN 4599156896' (a literal parcel id) alongside
    location_address 'WEDDINGTON ROAD'. Already fetched in the same
    response; must be kept, not dropped on the floor."""
    row = _row()
    row["supplemental_location"] = "PIN 4599156896"
    li = E._to_listing(row, "NC", "ACRES")
    assert li.raw["epa_frs"]["supplemental_location"] == "PIN 4599156896"


def test_missing_supplemental_location_is_none_not_a_crash():
    li = E._to_listing(_row(), "NC", "ACRES")
    assert li.raw["epa_frs"]["supplemental_location"] is None
