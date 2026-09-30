"""Locks in the 2026-09-30 fix: NC:Gaston's owner/mailing GIS spec now also
requests SQFT/YEARBLT/TOTVAL, and the generic building-spec/value extractors
recognize those bare Esri-CAMA field names.

Context: `counties_nc.gaston_vacant` already reads SQFT/YEARBLT off this exact
layer (PublicGIS/Parcels/FeatureServer/11) for its VacantImpro slice, but
`enrichment_owner_mailing` — which reaches EVERY Gaston lead, not just vacant
parcels — never requested those columns, so the generic
_extract_specs/_extract_value matchers (which already exist for exactly this
purpose) had nothing to work with. Live-verified 2026-09-30: 91,827 of 118,065
Gaston parcels (77.8%) carry SQFT>0.

No network calls here (CI-safe, no RUN_NETWORK_TESTS gate needed) — the live
round-trip against the real ArcGIS endpoint was verified manually during this
session and is not re-asserted in the committed suite.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_owner_mailing import (
    COUNTY_GIS,
    _extract_specs,
    _extract_value,
    _spec_out_fields,
)


def test_bare_sqft_field_name_matches_living_sqft_pattern():
    assert _extract_specs({"SQFT": 1102.0}) == {"living_sqft": 1102.0}


def test_bare_yearblt_field_name_matches_year_built_pattern():
    assert _extract_specs({"YEARBLT": 1972}) == {"year_built": 1972.0}


def test_gaston_real_shaped_row_extracts_specs_and_value():
    # Captured live 2026-09-30: PIN 3546-54-4082, 718 NORTON DR.
    attrs = {"PIN": "3546-54-4082", "PHYSSTRADD": "718 NORTON DR",
              "SQFT": 1102.0, "YEARBLT": 1972, "TOTVAL": 198260.0,
              "CURR_NAME1": "ADAMS CHRISTOPHER"}
    specs = _extract_specs(attrs)
    assert specs["living_sqft"] == 1102.0
    assert specs["year_built"] == 1972.0
    assert _extract_value(attrs) == 198260.0


def test_living_sqft_out_of_range_still_rejected():
    # Sanity guard unaffected by the new bare-name alternative: a 0/junk value
    # must still be rejected by the existing 200-30000 range check.
    assert _extract_specs({"SQFT": 50}) == {}
    assert _extract_specs({"SQFT": 0}) == {}


def test_gaston_spec_requests_the_new_fields():
    spec = COUNTY_GIS["NC:Gaston"]
    out_fields = set(_spec_out_fields(spec).split(","))
    assert {"SQFT", "YEARBLT", "TOTVAL"} <= out_fields
    # The original owner/mail/situs/parcel columns must still be requested —
    # the explicit out_fields string was a full replacement, not an addition,
    # so dropping one of these silently would break owner/mailing resolution.
    assert {"PIN", "CURR_NAME1", "CURR_NAME2", "CURR_ADDR1", "CURR_ADDR2",
            "CURR_CITY", "CURR_STATE", "CURR_ZIPCODE", "PHYSSTRADD"} <= out_fields


def test_other_counties_unaffected_by_bare_sqft_pattern():
    # The new bare "sq_?ft"/"year_?blt" alternatives are anchored full-name
    # matches, so a differently-named field (e.g. Spartanburg's LOT-style or a
    # qualifier-prefixed column) must NOT accidentally match.
    assert _extract_specs({"LOT_SQFT": 43560}) == {}
    assert _extract_specs({"GISAcres": 1.2}) == {}
