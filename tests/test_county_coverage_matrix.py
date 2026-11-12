"""scripts/county_coverage_matrix.py -- _family() matching.

This script is a near-duplicate of scripts/coverage_100_ledger.py's FAMILIES table,
predating its a22dc20c / bf38dd0c false-positive fixes and never updated when those
landed. It matches purely on SOURCE NAME fragments (no distress_stack signal gate at
all), so it inherited the confirmed over-broad-fragment false positives directly:

  * "zombie" (code_vacancy): zombie_properties.py is a DERIVED stalled-foreclosure
    signal (a stale lis pendens that never progressed to sale), not a
    code-enforcement/vacancy source.
  * "vacant" (code_vacancy): also matches gaston_vacant / lincoln_vacant /
    transylvania_vacant -- three county-GIS VACANT-LAND (unimproved lot, no
    structure) feeds, the opposite condition from code_vacancy.
  * bare "courtlistener" (bankruptcy): also matches national.courtlistener_civil, a
    federal CIVIL real-property/foreclosure docket scraper, never bankruptcy.

2026-09-30 fix mirrors coverage_100_ledger.py's own a22dc20c/bf38dd0c fixes exactly.
Nothing here touches the live board -- pure unit tests of `_family()`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import county_coverage_matrix as ccm  # noqa: E402


def test_gaston_vacant_land_is_not_code_vacancy_evidence():
    assert ccm._family("counties_nc.gaston_vacant") is None


def test_lincoln_vacant_land_is_not_code_vacancy_evidence():
    assert ccm._family("counties_nc.lincoln_vacant") is None


def test_transylvania_vacant_land_is_not_code_vacancy_evidence():
    assert ccm._family("counties_nc.transylvania_vacant") is None


def test_spartanburg_vacant_structure_registry_still_counts():
    """spartanburg_vacant is a real vacant-STRUCTURE registry (CAMA specs only exist on
    an improved parcel), not vacant land -- must keep matching by name."""
    assert ccm._family("counties_sc.spartanburg_vacant") == "code_vacancy"


def test_lincoln_code_violations_unaffected_by_the_vacant_land_exclusion():
    assert ccm._family("counties_nc.lincoln_code_violations") == "code_vacancy"


def test_zombie_properties_is_not_code_vacancy_evidence():
    """zombie_properties.py is a derived stalled-foreclosure signal, not
    code-enforcement/vacancy -- must not count, and must not fall through to some
    other family either."""
    assert ccm._family("counties_sc.zombie_properties") is None


def test_courtlistener_civil_is_not_bankruptcy_evidence():
    """national.courtlistener_civil is a federal CIVIL real-property/foreclosure
    docket scraper (nature-of-suit 220/230/240/290), never bankruptcy."""
    assert ccm._family("national.courtlistener_civil") is None


def test_courtlistener_bankruptcy_still_counts_via_the_bankruptcy_fragment():
    assert ccm._family("national.courtlistener_bankruptcy") == "bankruptcy"


def test_courtlistener_adversary_still_counts_via_its_own_fragment():
    assert ccm._family("national.courtlistener_adversary") == "bankruptcy"


def test_real_code_violation_and_condemn_sources_unaffected():
    assert ccm._family("counties_nc.henderson_code_violations") == "code_vacancy"
    assert ccm._family("counties_sc.spartanburg_condemned") == "code_vacancy"


def test_none_source_is_safe():
    assert ccm._family(None) is None
    assert ccm._family("") is None
