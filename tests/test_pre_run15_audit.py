"""Pin the two pre-Run-#15 audit fixes:

1. All scrapers added in this PR are in DATELESS_OK_SOURCES — otherwise
   _active_only would drop their listings whenever sale_date is missing
   (which is most of the time for monthly/annual/event-driven cadence).

2. The 13 NC counties added to nc_ecourts_lis_pendens.TARGET_COUNTIES
   are also in config.NC_COUNTIES so listings from those counties pass
   _in_scope and don't get silently dropped.
"""
from __future__ import annotations

from foreclosure_scraper.main import DATELESS_OK_SOURCES, OCEANFRONT_COASTAL_COUNTIES
from foreclosure_scraper.config import NC_COUNTIES, in_scope
from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_lis_pendens import (
    TARGET_COUNTIES as NC_ECOURTS_TARGETS,
)

# 2026-06-25 — COASTAL NC track. These five eCourts targets are deliberately
# NOT in config.NC_COUNTIES: they re-enter scope through the oceanfront gate in
# main._in_scope (OCEANFRONT_COASTAL_COUNTIES) rather than the footprint allow-
# list, per explicit user direction to cover the coast. Querying their Tyler
# facets is intentional; the WNC footprint targets must still all be in scope.
NC_ECOURTS_COASTAL = {"Brunswick", "Pender", "Onslow", "Carteret", "Dare",
                      "Currituck", "Hyde", "New Hanover"}


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
    """Every WNC-footprint county the NC eCourts scraper queries must be in
    config.NC_COUNTIES — otherwise its listings fail _in_scope and get dropped
    before any enrichment can save them. The five coastal targets are exempt:
    they re-enter via the oceanfront gate, not the footprint allow-list."""
    nc_county_names = {c.name for c in NC_COUNTIES}
    footprint_targets = set(NC_ECOURTS_TARGETS) - NC_ECOURTS_COASTAL
    out_of_scope = footprint_targets - nc_county_names
    assert not out_of_scope, (
        f"NC eCourts queries these WNC counties but they're NOT in "
        f"config.NC_COUNTIES — listings will be dropped: {sorted(out_of_scope)}"
    )
    # The coastal exception set must all be recognized oceanfront counties.
    for c in NC_ECOURTS_COASTAL:
        assert (c, "NC") in OCEANFRONT_COASTAL_COUNTIES, (
            f"coastal eCourts target {c} is neither in NC_COUNTIES nor an "
            f"OCEANFRONT_COASTAL_COUNTIES entry — it would be silently dropped"
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
    """NC_COUNTIES should be a SUPERSET of the WNC-footprint eCourts targets
    (coastal targets excepted — they ride the oceanfront gate). If a new
    footprint county is queried but not added to config, this catches it."""
    nc_county_names = {c.name for c in NC_COUNTIES}
    for ec in set(NC_ECOURTS_TARGETS) - NC_ECOURTS_COASTAL:
        assert ec in nc_county_names, (
            f"NC eCourts footprint target '{ec}' not present in config.NC_COUNTIES"
        )
