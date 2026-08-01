"""Parse-time geo gate shared by the statewide trustee-firm calendars.

The gate is footprint ∪ coastal, deliberately: `main._in_scope` admits
coastal-county rows from these firms through the oceanfront lane, so filtering
to the 18 counties alone at parse time would delete rows the engine still wants
to judge. The drift test below is the guard that keeps the scraper-local coastal
mirror identical to main's — if someone edits one set, the suite fails.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.law_firms._footprint import (
    COASTAL_COUNTIES,
    in_footprint,
    is_coastal,
    keep,
    normalize_county,
)


def test_normalize_county_strips_state_suffix_and_county_word():
    # Hutchens writes "Yadkin, NC"; Brock writes the slug "new-hanover";
    # other feeds write "Gaston County".
    assert normalize_county("Yadkin, NC") == "Yadkin"
    assert normalize_county("Gaston County") == "Gaston"
    assert normalize_county("new hanover") == "New Hanover"
    assert normalize_county("  buncombe  ") == "Buncombe"
    assert normalize_county("") is None
    assert normalize_county(None) is None


def test_normalize_county_canonicalizes_internal_capitals():
    """`.title()` alone would produce "Mcdowell".

    A dozen enrichments (ArcGIS parcel layer, FHFA value, geocode centroid,
    buyer match, Helene damage) match the exact string "McDowell", so a
    title-cased county silently skips all of them.
    """
    assert normalize_county("mcdowell") == "McDowell"
    assert normalize_county("McDowell, NC") == "McDowell"
    assert normalize_county("MCDOWELL COUNTY") == "McDowell"


def test_in_footprint_matches_the_18_tracked_counties():
    assert in_footprint("Buncombe, NC", "NC") is True
    assert in_footprint("Spartanburg", "SC") is True
    assert in_footprint("Gaston County", "NC") is True
    # Out of footprint entirely
    assert in_footprint("Yadkin", "NC") is False
    assert in_footprint("Richland", "SC") is False
    # Explicitly denied in config.SCOPE_DENY_COUNTIES
    assert in_footprint("Wake", "NC") is False
    assert in_footprint("Greenville", "SC") is False


def test_coastal_counties_pass_the_gate_but_are_not_in_footprint():
    for county, state in (("Carteret", "NC"), ("Horry", "SC"), ("Beaufort", "SC")):
        assert is_coastal(county, state) is True
        assert in_footprint(county, state) is False
        assert keep(county, state) is True


def test_keep_rejects_plain_out_of_footprint_rows():
    assert keep("Yadkin", "NC") is False
    assert keep("Richland", "SC") is False
    assert keep("Greenville", "SC") is False   # denied, and not coastal
    assert keep(None, "NC") is False
    assert keep("Buncombe", None) is False


def test_coastal_mirror_has_not_drifted_from_main():
    """The scraper-local coastal set must equal main.OCEANFRONT_COASTAL_COUNTIES.

    A scraper can't import main (main imports the scraper registry), so the set
    is duplicated. This test is what stops the copy from going stale.
    """
    from foreclosure_scraper.main import OCEANFRONT_COASTAL_COUNTIES

    assert COASTAL_COUNTIES == OCEANFRONT_COASTAL_COUNTIES
