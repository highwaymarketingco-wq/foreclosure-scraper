"""scripts/source_signal_county_matrix.py -- _family() matching.

Another near-duplicate of scripts/coverage_100_ledger.py's FAMILIES table (it feeds
"matrix.js" for the "County signal ledger" artifact dashboard), predating that
script's a22dc20c / c64d7530 / bf38dd0c false-positive fixes and never updated when
they landed. Source-name-fragment matching only (no distress_stack signal gate), so
it inherited the confirmed false positives directly -- see the SIGNAL_FAMILIES
comment in the script for the full audit trail. 2026-09-30 fix mirrors
coverage_100_ledger.py's own fixes. Pure unit tests of `_family()`; no board read.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import source_signal_county_matrix as ssm  # noqa: E402


# ---- code_vacancy: vacant-LAND sources + zombie_properties -----------------------------

def test_gaston_vacant_land_is_not_code_vacancy_evidence():
    assert ssm._family("counties_nc.gaston_vacant") == "other"


def test_lincoln_vacant_land_is_not_code_vacancy_evidence():
    assert ssm._family("counties_nc.lincoln_vacant") == "other"


def test_transylvania_vacant_land_is_not_code_vacancy_evidence():
    assert ssm._family("counties_nc.transylvania_vacant") == "other"


def test_spartanburg_vacant_structure_registry_still_counts():
    assert ssm._family("counties_sc.spartanburg_vacant") == "code_vacancy"


def test_zombie_properties_is_not_code_vacancy_evidence():
    assert ssm._family("counties_sc.zombie_properties") == "other"


# ---- bankruptcy: bare "courtlistener" narrowed ------------------------------------------

def test_courtlistener_civil_is_not_bankruptcy_evidence():
    """national.courtlistener_civil is a federal CIVIL real-property/foreclosure docket
    scraper (nature-of-suit 220/230/240/290), never bankruptcy."""
    assert ssm._family("national.courtlistener_civil") == "other"


def test_courtlistener_bankruptcy_still_counts():
    assert ssm._family("national.courtlistener_bankruptcy") == "bankruptcy"


def test_courtlistener_adversary_still_counts():
    assert ssm._family("national.courtlistener_adversary") == "bankruptcy"


# ---- probate_estate: hibid_real_estate excluded -----------------------------------------

def test_hibid_real_estate_is_not_probate_estate_evidence():
    """national.hibid_real_estate is a generic AUCTION-category real-estate aggregator
    (its own slug carries "real_estate") -- the "estate" substring is coincidental, not
    a decedent-estate signal."""
    assert ssm._family("national.hibid_real_estate", "auction") == "other"


def test_dedicated_estate_sources_still_count():
    assert ssm._family("national.estate_sales") == "probate_estate"
    assert ssm._family("counties_nc.nc_heir_estate_parcels") == "probate_estate"
    assert ssm._family("counties_nc.nc_ecourts_estates") == "probate_estate"


# ---- liens_judgments: ROD sweep sources gated on listing_type ---------------------------

def test_rod_acclaim_lien_row_counts_as_liens_judgments():
    assert ssm._family("counties_sc.sc_rod_acclaim", "tax_lien") == "liens_judgments"


def test_rod_acclaim_lis_pendens_row_does_not_count_as_liens_judgments():
    """The SAME sc_rod_acclaim scraper also emits lis-pendens/foreclosure-deed/probate
    rows off the same sweep -- those must not count as liens just because they share a
    source with real lien rows."""
    assert ssm._family("counties_sc.sc_rod_acclaim", "lis_pendens") != "liens_judgments"


def test_rod_cott_probate_row_does_not_count_as_liens_judgments():
    assert ssm._family("counties_sc.sc_rod_cott", "probate_notice") != "liens_judgments"


def test_rod_logan_lien_row_counts_as_liens_judgments():
    assert ssm._family("counties_nc.nc_rod_logan", "tax_lien") == "liens_judgments"


def test_rod_logan_foreclosure_sale_row_does_not_count_as_liens_judgments():
    assert ssm._family("counties_nc.nc_rod_logan", "foreclosure_sale") != "liens_judgments"


def test_dedicated_lien_registry_source_still_counts_with_no_listing_type():
    """A genuinely lien-specific source (not a ROD sweep) still counts via its own
    fragment, with no listing_type gate needed."""
    assert ssm._family("counties_sc.sc_dew_lien_registry") == "liens_judgments"
    assert ssm._family("national.nc_sos_ucc") == "liens_judgments"


def test_rod_substitute_trustee_is_mortgage_foreclosure_not_liens():
    """nc_rod_substitute_trustee.py never emits a LIEN-typed row (always LIS_PENDENS or
    FORECLOSURE_SALE) -- it is real mortgage_foreclosure evidence (pre/post-sale
    foreclosure recordings), matched via the earlier-checked "substitute_trustee"
    fragment, not liens_judgments."""
    assert ssm._family("counties_nc.nc_rod_substitute_trustee", "lis_pendens") == "mortgage_foreclosure"
    assert ssm._family("counties_nc.nc_rod_substitute_trustee", "foreclosure_sale") == "mortgage_foreclosure"


# ---- safety -------------------------------------------------------------------------

def test_none_source_is_safe():
    assert ssm._family(None) == "other"
    assert ssm._family("") == "other"
