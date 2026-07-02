"""Spartanburg County condemned / dilapidated-structure distress signal.

Built 2026-07-02. The county's dedicated Condemned_Properties MapServer is a
live-but-empty shell (0 layers, blank render — see module docstring), so the
signal is sourced from the CAMA_Parcels FeatureServer condition code
(ConditionFactor DL=DELAPITATED -> condemned, VP=VERY POOR -> very-poor).

Fixtures below are shaped exactly like the live ArcGIS feature JSON
(attributes + geometry rings), captured from the real service 2026-07-02.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_sc.spartanburg_condemned import (
    SpartanburgCondemned,
)

SLUG = "counties_sc.spartanburg_condemned"


def _feat(attrs: dict, rings=None) -> dict:
    geom = {"rings": rings} if rings else {}
    return {"attributes": attrs, "geometry": geom}


# A real dilapidated (DL) row, absentee owner (mails from a different metro).
_DL_ABSENTEE = _feat(
    {
        "GISParcelNumber": "6189-56-5809.33",
        "MAPNUMBER": "1-23-14-006.00",
        "PARCELNUMBER": "6",
        "OwnerName": "CANTERBURY JONI J",
        "PropertyLocation": "196 MAYSONS COVE DR INMAN",
        "StreetAddress": "421 WATERCREST CT",
        "City": "CHARLOTTE",
        "State": "NC",
        "Zip": "28202",
        "YearBuilt": 1993,
        "LivingArea": 1450,
        "BedRooms": 3,
        "FullBaths": 2,
        "ConditionFactor": "DL",
        "CDUC": "DELAPITATED",
        "PropertyType": "4OOR SINGLE FAM",
        "CurrentAppraisedBuildingValue": 273800.0,
        "CurrentAppraisedLandValue": 40000.0,
    },
    rings=[[[-82.05161487, 35.11804400], [-82.0515, 35.1181], [-82.0517, 35.1179]]],
)

# A very-poor (VP) row, resident local owner.
_VP_LOCAL = _feat(
    {
        "GISParcelNumber": "7143-82-7790.79",
        "OwnerName": "STEPHENS PAUL",
        "PropertyLocation": "121 CHAPEL ST GLENDALE",
        "StreetAddress": "121 CHAPEL ST",
        "City": "SPARTANBURG",
        "State": "SC",
        "Zip": "29302",
        "YearBuilt": 1940,
        "LivingArea": 980,
        "ConditionFactor": "VP",
        "CDUC": "VERY POOR",
        "PropertyType": "6RGR SINGLE FAM",
        "CurrentAppraisedBuildingValue": 12000.0,
        "CurrentAppraisedLandValue": 8000.0,
    },
)

# Government owner — must be dropped.
_GOV_ROW = _feat(
    {
        "GISParcelNumber": "7000-00-0000.00",
        "OwnerName": "CITY OF SPARTANBURG",
        "PropertyLocation": "0 SOME ST SPARTANBURG",
        "ConditionFactor": "DL",
        "CDUC": "DELAPITATED",
    },
)

# Vacant-land dilapidated row (situs starts with "0 ", no living area) -> LAND.
_LAND_ROW = _feat(
    {
        "GISParcelNumber": "7023-03-7010.84",
        "OwnerName": "BURGESS CARROLL EDWARD",
        "PropertyLocation": "0 BURGESS RD ENOREE",
        "StreetAddress": "190 BURGESS RD",
        "City": "ENOREE",
        "State": "SC",
        "Zip": "29335",
        "YearBuilt": 0,
        "LivingArea": 0,
        "ConditionFactor": "DL",
        "CDUC": "DELAPITATED",
    },
)


def _s() -> SpartanburgCondemned:
    return SpartanburgCondemned()


# ---------------------------------------------------------------------------
# Condemned (DL) row -> raw['condemned'] signal
# ---------------------------------------------------------------------------
def test_dilapidated_sets_condemned_signal():
    li = _s()._to_listing(_DL_ABSENTEE)
    assert li is not None
    assert li.source == SLUG
    assert li.state == "SC"
    assert li.county == "Spartanburg"
    assert li.parcel_id == "6189-56-5809.33"
    assert li.street_address == "196 MAYSONS COVE DR INMAN"
    assert li.defendant == "CANTERBURY JONI J"
    assert li.owner_name == "CANTERBURY JONI J"
    assert li.listing_type == ListingType.UNKNOWN
    assert li.property_kind == PropertyKind.SINGLE_FAMILY
    # The distress-score hook: raw['condemned'] -> code_enforcement (w=14).
    assert li.raw.get("condemned") is True
    assert li.raw.get("code_enforcement") is True
    assert li.raw.get("distressed") is True
    sig = li.raw.get("condemned_signal")
    assert sig and sig["tier"] == "condemned"
    assert sig["condition_code"] == "DL"
    assert sig["condition_label"] == "DELAPITATED"


def test_dilapidated_carries_specs_value_and_coords():
    li = _s()._to_listing(_DL_ABSENTEE)
    assert li.year_built == 1993
    assert li.living_sqft == 1450
    # market_value = appraised building + land
    assert li.market_value == pytest.approx(313800.0)
    assert li.raw["cama_specs"]["bedrooms"] == 3
    assert li.raw["cama_specs"]["full_baths"] == 2
    # centroid-ish from first ring vertex, in lon/lat
    assert li.longitude == pytest.approx(-82.05161487, abs=1e-5)
    assert li.latitude == pytest.approx(35.11804400, abs=1e-5)


def test_absentee_out_of_state_owner_flagged():
    li = _s()._to_listing(_DL_ABSENTEE)
    assert li.raw.get("absentee") is True
    assert li.raw.get("owner_mailing") == "421 WATERCREST CT CHARLOTTE NC 28202"


# ---------------------------------------------------------------------------
# Very-poor (VP) row -> distressed only, NOT condemned
# ---------------------------------------------------------------------------
def test_very_poor_is_distressed_but_not_condemned():
    li = _s()._to_listing(_VP_LOCAL)
    assert li is not None
    assert li.raw.get("distressed") is True
    assert "condemned" not in li.raw          # VP does not set the condemned flag
    assert "code_enforcement" not in li.raw
    assert li.raw["condemned_signal"]["tier"] == "very_poor"
    # Local Spartanburg-metro owner is NOT absentee.
    assert li.raw.get("absentee") is False


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def test_government_owner_dropped():
    assert _s()._to_listing(_GOV_ROW) is None


def test_vacant_land_dilapidated_classified_as_land():
    li = _s()._to_listing(_LAND_ROW)
    assert li is not None
    assert li.property_kind == PropertyKind.LAND
    # still a condemned signal on the land parcel
    assert li.raw.get("condemned") is True


def test_parcel_id_normalizes_to_shared_dedupe_key():
    # The dashed GISParcelNumber must collapse to the same dedupe key as the
    # compact 12-digit county PIN other Spartanburg sources emit, so the
    # condemned flag MERGES onto an existing parcel instead of duplicating it.
    from foreclosure_scraper.models import _normalize_parcel

    li = _s()._to_listing(_DL_ABSENTEE)
    assert _normalize_parcel(li.parcel_id) == _normalize_parcel("618956580933")


# ---------------------------------------------------------------------------
# Registration + live smoke (network-gated)
# ---------------------------------------------------------------------------
def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    slugs = {s.slug for s in all_scrapers()}
    assert SLUG in slugs


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live Spartanburg CAMA ArcGIS — slow; set RUN_NETWORK_TESTS=1",
)
def test_live_yields_condemned_rows_with_parcels():
    rows = asyncio.run(SpartanburgCondemned().fetch())
    rows = list(rows)
    assert rows, "expected dilapidated/very-poor parcels from Spartanburg CAMA"
    for li in rows:
        assert li.state == "SC"
        assert li.county == "Spartanburg"
        assert li.parcel_id or li.street_address
    condemned = [li for li in rows if (li.raw or {}).get("condemned")]
    assert condemned, "expected at least one DL/condemned parcel"
    # every condemned row carries the code_enforcement distress hook
    for li in condemned:
        assert li.raw.get("code_enforcement") is True
