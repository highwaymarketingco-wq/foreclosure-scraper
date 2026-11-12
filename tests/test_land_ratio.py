"""Land-value share enricher (Dirty Deeds Tier A #11)."""
from __future__ import annotations

from foreclosure_scraper.enrichment_land_ratio import compute_land_ratio, enrich_land_ratio
from foreclosure_scraper.models import Listing, ListingType


def _mk(raw):
    return Listing(source="x", source_url="u", listing_type=ListingType.TAX_LIEN,
                   state="NC", county="Gaston", raw=raw)


def test_land_heavy_when_dirt_dominates_a_real_structure():
    li = _mk({"gis_attrs_full": {"CurrentAppraisedLandValue": "80,000",
                                 "CurrentAppraisedBuildingValue": "40000"}})
    b = compute_land_ratio(li)
    assert b["land_share"] == round(80000 / 120000, 3)
    assert b["land_heavy"] is True and b["vacant_land"] is False


def test_structure_dominant_parcel_is_not_land_heavy():
    li = _mk({"gis_attrs_full": {"CurrentAppraisedLandValue": 30000,
                                 "CurrentAppraisedBuildingValue": 170000}})
    assert compute_land_ratio(li)["land_heavy"] is False


def test_missing_improvement_value_yields_no_ratio_not_a_guess():
    li = _mk({"gis_attrs_full": {"CurrentAppraisedLandValue": 50000}})
    assert compute_land_ratio(li) is None


def test_gaston_vacant_code_makes_missing_improvement_a_real_zero():
    li = _mk({"gaston_gis": {"FMV_LAND": 25000, "FMV_IMPRV": None, "VacantImpro": "V"}})
    b = compute_land_ratio(li)
    assert b["vacant_land"] is True and b["land_heavy"] is False
    assert b["land_share"] == 1.0


def test_gaston_improved_with_no_improvement_value_is_unknown():
    li = _mk({"gaston_gis": {"FMV_LAND": 25000, "FMV_IMPRV": None, "VacantImpro": "I"}})
    assert compute_land_ratio(li) is None


def test_no_land_value_or_no_blocks_is_a_noop():
    assert compute_land_ratio(_mk({})) is None
    assert compute_land_ratio(_mk({"gis_attrs_full": {"CurrentAppraisedLandValue": 0,
                                                       "CurrentAppraisedBuildingValue": 5}})) is None


def test_enrich_tags_only_computable_rows_and_never_drops():
    a = _mk({"gis_attrs_full": {"CurrentAppraisedLandValue": 90000,
                                "CurrentAppraisedBuildingValue": 10000}})
    b = _mk({})
    rows = [a, b]
    stats = enrich_land_ratio(rows)
    assert len(rows) == 2
    assert stats == {"tagged": 1, "vacant_land": 0, "land_heavy": 1}
    assert "land_ratio" not in b.raw
