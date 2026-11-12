"""Unit tests for the county-GIS appraised/market value extractor.

Locks in the priority order, the land+improvement sum fallback (counties like
McDowell expose only components), and the traps we must avoid: SC Spartanburg's
'Assessment' is a class string ('4% OO RES IM'), and 0/exempt parcels.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_owner_mailing import _extract_value


def test_prefers_total_market_value():
    a = {"TotalMarketValue": 526900, "AppraisedValue": 500000, "LandValue": 90000}
    assert _extract_value(a) == 526900.0


def test_appraised_value_when_no_market():
    assert _extract_value({"AppraisedValue": 464500, "LandValue": 90000}) == 464500.0


def test_total_tax_value():
    # Polk-style: a total-tax field beats the land-only field.
    assert _extract_value({"LAND_VALUE": 83420, "TOTAL_TAX_VALUE": 206613}) == 206613.0


def test_assessed_v_field():
    # Transylvania exposes ASSESSED_V.
    assert _extract_value({"LAND_VALUE": 60000, "ASSESSED_V": 180000, "BUILDING_V": 120000}) == 180000.0


def test_land_plus_improvement_sum():
    # McDowell exposes only components; they must be summed.
    assert _extract_value({"landval": 47460, "improvval": 26220}) == 73680.0


def test_building_v_summed_when_no_total():
    assert _extract_value({"LAND_VALUE": 60000, "BUILDING_V": 120000}) == 180000.0


def test_spartanburg_assessment_class_string_is_skipped():
    # 'Assessment' here is an assessment-CLASS code, not dollars.
    assert _extract_value({"Assessment": "4% OO RES IM"}) is None


def test_zero_and_exempt_rejected():
    assert _extract_value({"TotalMarketValue": 0, "LandValue": 0}) is None


def test_absurd_value_rejected():
    assert _extract_value({"TotalMarketValue": 99_000_000_000}) is None


def test_empty_attrs():
    assert _extract_value({}) is None
    assert _extract_value(None) is None  # noqa


def test_land_only_below_floor_rejected():
    # A lone tiny land value under the $1k floor is not a usable property value.
    assert _extract_value({"landval": 500}) is None


# ---- NC OneMap fallback (2026-06-22) ----
from foreclosure_scraper.enrichment_owner_mailing import (  # noqa: E402
    NC_ONEMAP, _county_clause,
)
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


def test_extract_value_handles_onemap_parval():
    assert _extract_value({"parval": 492600.0, "landval": 50000, "improvval": 442600}) == 492600.0


def test_onemap_parval_zero_falls_back_to_components():
    assert _extract_value({"parval": 0.0, "landval": 50000, "improvval": 30000}) == 80000.0


def test_county_clause_pins_statewide_layer_to_county():
    li = Listing(source="t", source_url="http://x",
                 listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Mitchell")
    assert _county_clause(NC_ONEMAP, li) == " AND UPPER(cntyname)='MITCHELL'"


def test_county_clause_empty_when_no_county_field():
    li = Listing(source="t", source_url="http://x",
                 listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Mitchell")
    assert _county_clause({"url": "x"}, li) == ""  # county-specific layer needs no filter


def test_onemap_spec_shape():
    assert NC_ONEMAP["county_field"] == "cntyname"
    assert "ownname" in NC_ONEMAP["owner"]
    assert NC_ONEMAP["source_label"] == "nc_onemap"
