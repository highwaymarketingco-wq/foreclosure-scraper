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
from foreclosure_scraper.config import in_scope, in_scope_distressed
from foreclosure_scraper.validation import NC_COUNTIES as ALL_NC_COUNTIES
from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_lis_pendens import (
    TARGET_COUNTIES as NC_ECOURTS_TARGETS,
)

# 2026-09-23: the coastal-vs-footprint distinction this test file used to
# track (a coastal-target exemption set) no longer applies -- TARGET_COUNTIES
# is now all 100 NC counties, all admitted via config.in_scope_distressed()
# rather than a mix of the footprint allow-list and the oceanfront gate. See
# test_nc_ecourts_targets_all_in_scope below.


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
    """Every county the NC eCourts scraper queries must actually pass this
    source's real scope gate — otherwise its listings get dropped before any
    enrichment can save them.

    2026-09-23: TARGET_COUNTIES widened from a 22-county WNC+coastal
    footprint to all 100 NC counties (docs/coverage_gap_build_plan_
    2026-09-23.md item 1). This source's listing types (LIS_PENDENS,
    TAX_LIEN, DIVORCE_NOTICE) are not in main._FLIP_LISTING_TYPES, so
    main._county_in_scope() routes them through config.in_scope_distressed()
    — which admits ANY real NC county, not the narrow config.NC_COUNTIES
    flip footprint this test used to check against. Checking against the
    old narrow list would now fail for 78 legitimately-added counties even
    though they pass the gate this source's rows actually go through."""
    out_of_scope = [c for c in NC_ECOURTS_TARGETS if not in_scope_distressed(c, "NC")]
    assert not out_of_scope, (
        f"NC eCourts queries these counties but they fail "
        f"config.in_scope_distressed() — listings will be dropped: {sorted(out_of_scope)}"
    )
    # Every target must also be a real, canonical NC county name.
    nc_all_names = set(ALL_NC_COUNTIES)
    unknown = [c for c in NC_ECOURTS_TARGETS if c not in nc_all_names]
    assert not unknown, f"TARGET_COUNTIES has non-canonical county names: {unknown}"


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
    """validation.NC_COUNTIES (the canonical 100-county set TARGET_COUNTIES is
    sourced from, see nc_ecourts_lis_pendens.py) should be a SUPERSET of every
    eCourts target. If a typo'd or non-canonical county name is ever added to
    TARGET_COUNTIES directly (bypassing the `sorted(_ALL_NC_COUNTIES)` source),
    this catches it."""
    nc_all_names = set(ALL_NC_COUNTIES)
    for ec in NC_ECOURTS_TARGETS:
        assert ec in nc_all_names, (
            f"NC eCourts target '{ec}' not present in validation.NC_COUNTIES"
        )
    assert set(NC_ECOURTS_TARGETS) == nc_all_names, (
        "TARGET_COUNTIES should now equal the full validation.NC_COUNTIES set "
        "(2026-09-23 statewide widening) -- diff: "
        f"{nc_all_names.symmetric_difference(NC_ECOURTS_TARGETS)}"
    )
