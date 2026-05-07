"""Pin the two pre-Run-#15 audit fixes:

1. All scrapers added in this PR are in DATELESS_OK_SOURCES — otherwise
   _active_only would drop their listings whenever sale_date is missing
   (which is most of the time for monthly/annual/event-driven cadence).

2. The 13 NC counties added to nc_ecourts_lis_pendens.TARGET_COUNTIES
   are also in config.NC_COUNTIES so listings from those counties pass
   _in_scope and don't get silently dropped.
"""
from __future__ import annotations

from foreclosure_scraper.main import DATELESS_OK_SOURCES
from foreclosure_scraper.config import NC_COUNTIES, in_scope
from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_lis_pendens import (
    TARGET_COUNTIES as NC_ECOURTS_TARGETS,
)


# Sources added in the May 2026 expansion. All emit listings that
# typically lack sale_date — must be in DATELESS_OK_SOURCES.
NEW_SOURCES_2026_05 = {
    "counties_sc.sc_courtrosters",
    "counties_nc.wake_tax",
    "counties_nc.forsyth_tax",
    "counties_nc.guilford_tax",
    "counties_nc.new_hanover_tax",
    "counties_nc.durham_tax",
    "counties_nc.nc_rod_substitute_trustee",
    "reo.usda_rd",
    "reo.treasury_seized",
    "reo.vrm_va_reo",
    "city_websites.charlotte_demolition",
    "national.courtlistener_civil",
    "national.courtlistener_adversary",
}


def test_all_new_sources_in_dateless_ok():
    """Without these entries, _active_only would drop any listing from
    these sources that has sale_date=None. Most do — they list inventory
    that's not yet on a specific auction date."""
    missing = NEW_SOURCES_2026_05 - DATELESS_OK_SOURCES
    assert not missing, f"new sources missing from DATELESS_OK_SOURCES: {missing}"


def test_nc_ecourts_targets_all_in_scope():
    """Every county the NC eCourts scraper queries must also be in
    config.NC_COUNTIES — otherwise listings from those counties fail
    _in_scope and get dropped before any enrichment can save them."""
    nc_county_names = {c.name for c in NC_COUNTIES}
    out_of_scope = set(NC_ECOURTS_TARGETS) - nc_county_names
    assert not out_of_scope, (
        f"NC eCourts queries these counties but they're NOT in "
        f"config.NC_COUNTIES — listings will be dropped: {sorted(out_of_scope)}"
    )


def test_in_scope_works_for_kept_counties():
    """Spot-check the NC counties currently in the user's target territory.
    The 2026-05-07 scope rollback removed Wake / Forsyth / Guilford /
    Durham / Cumberland / Alamance / Cabarrus / Iredell / Pitt / Johnston /
    Union NC — those are 1.5-4h east of the upstate-SC / WNC corridor."""
    for county in ("Henderson", "Buncombe", "Mecklenburg", "Gaston",
                   "Cleveland", "New Hanover", "Brunswick", "Onslow"):
        assert in_scope(county, "NC"), f"NC county {county} should be in scope"


def test_dropped_eastern_counties_no_longer_in_scope():
    """The 11 eastern NC counties pruned 2026-05-07 must NOT pass _in_scope
    so we stop pulling 890 listings/run from outside the user's territory."""
    for county in ("Wake", "Forsyth", "Guilford", "Durham", "Cumberland",
                   "Alamance", "Iredell", "Cabarrus", "Pitt", "Johnston"):
        assert not in_scope(county, "NC"), (
            f"NC county {county} was dropped from scope but in_scope still "
            f"returns True"
        )


def test_county_count_matches_ecourts_target_count():
    """Exact-match: NC_COUNTIES should be a SUPERSET of NC_ECOURTS_TARGETS,
    not just intersect. If the eCourts list grows in the future, this test
    catches the omission."""
    nc_county_names = {c.name for c in NC_COUNTIES}
    for ec in NC_ECOURTS_TARGETS:
        assert ec in nc_county_names, (
            f"NC eCourts target '{ec}' not present in config.NC_COUNTIES"
        )
