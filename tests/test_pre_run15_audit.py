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


# Sources that emit listings which typically lack sale_date — these must
# be in DATELESS_OK_SOURCES or _active_only would drop them. Filtered to
# currently-registered scrapers at test time so deleted scrapers (wake_tax,
# durham_tax, charlotte_demolition, etc., pruned in later scope cuts) don't
# break the audit.
DATELESS_EMITTING_SOURCES = {
    "counties_nc.nc_rod_substitute_trustee",
    "reo.usda_rd",
    "reo.treasury_seized",
    "reo.vrm_va_reo",
    "national.courtlistener_civil",
    "national.courtlistener_adversary",
}


def test_all_new_sources_in_dateless_ok():
    """Every still-registered dateless-emitting source must be in
    DATELESS_OK_SOURCES, else _active_only drops its sale_date=None rows."""
    from foreclosure_scraper.scrapers._registry import all_scrapers
    registered = {s.slug for s in all_scrapers()}
    expected = DATELESS_EMITTING_SOURCES & registered
    missing = expected - DATELESS_OK_SOURCES
    assert not missing, f"dateless sources missing from DATELESS_OK_SOURCES: {missing}"


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
    """Spot-check the 11 in-scope NC counties. Eastern NC + Charlotte +
    Madison/Yancey were pruned in the 2026-05-07 rollbacks; coastal NC
    (New Hanover/Brunswick/Onslow) was pruned 2026-05-15."""
    for county in ("Henderson", "Buncombe", "Gaston", "Cleveland", "Rutherford",
                   "Polk", "Transylvania", "Burke", "McDowell", "Lincoln", "Mitchell"):
        assert in_scope(county, "NC"), f"NC county {county} should be in scope"


def test_dropped_counties_no_longer_in_scope():
    """All counties pruned across 2026-05-07a (eastern NC) + 2026-05-07b
    (Charlotte + Madison/Yancey + Haywood/Abbeville denylist) must NOT
    pass _in_scope so we stop pulling them through any path."""
    # 2026-05-07a — eastern NC
    for county in ("Wake", "Forsyth", "Guilford", "Durham", "Cumberland",
                   "Alamance", "Iredell", "Cabarrus", "Pitt", "Johnston"):
        assert not in_scope(county, "NC"), (
            f"NC county {county} was dropped from scope but in_scope still "
            f"returns True"
        )
    # 2026-05-07b — Charlotte + adjacent WNC pruning
    for county in ("Mecklenburg", "Madison", "Yancey", "Haywood"):
        assert not in_scope(county, "NC"), (
            f"NC county {county} was dropped from scope but in_scope still "
            f"returns True"
        )
    # SC: Abbeville is on the deny list (already not in SC_COUNTIES)
    assert not in_scope("Abbeville", "SC")


def test_county_count_matches_ecourts_target_count():
    """Exact-match: NC_COUNTIES should be a SUPERSET of NC_ECOURTS_TARGETS,
    not just intersect. If the eCourts list grows in the future, this test
    catches the omission."""
    nc_county_names = {c.name for c in NC_COUNTIES}
    for ec in NC_ECOURTS_TARGETS:
        assert ec in nc_county_names, (
            f"NC eCourts target '{ec}' not present in config.NC_COUNTIES"
        )
