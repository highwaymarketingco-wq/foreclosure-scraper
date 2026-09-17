"""ACS ZCTA demographic enricher — playbook Tier 1 #2 (income/home value/
owner-occ/vacancy/year-built), income/value/year-built pulled straight from
the response; owner-occ and vacancy are computed ratios, so their correctness
depends on getting the numerator/denominator pair right.
"""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.enrichment_census_demographics import (
    _parse_acs_row,
    _sane,
    enrich_census_demographics,
    _zip_cache,
)

_HEADER = ["B19013_001E", "B25077_001E", "B25003_001E", "B25003_002E",
           "B25002_001E", "B25002_003E", "B25035_001E", "NAME",
           "zip code tabulation area"]


def _row(income, value, occ_total, owner_occ, units_total, vacant, year_built):
    return [income, value, occ_total, owner_occ, units_total, vacant,
            year_built, "ZCTA5 28801", "28801"]


def test_parses_real_asheville_response():
    # Live-verified 2026-09-17 against ZCTA5 28801.
    row = _row("51125", "481400", "6081", "2232", "8490", "2409", "1963")
    out = _parse_acs_row(_HEADER, row)
    assert out["median_household_income"] == 51125
    assert out["median_home_value"] == 481400
    assert out["owner_occupied_pct"] == round(2232 / 6081 * 100, 1)
    assert out["vacant_housing_pct"] == round(2409 / 8490 * 100, 1)
    assert out["median_year_built"] == 1963


def test_missing_field_in_header_returns_none():
    short_header = _HEADER[:-3]  # drop a required ACS var
    out = _parse_acs_row(short_header, ["51125"])
    assert out is None


def test_null_acs_cell_is_dropped_not_zero():
    row = _row("-", "481400", "6081", "2232", "8490", "2409", "1963")
    out = _parse_acs_row(_HEADER, row)
    assert "median_household_income" not in out
    assert out["median_home_value"] == 481400


def test_owner_occ_over_total_is_rejected_as_bad_data():
    # owner_occ > occ_total is internally inconsistent -- never trust it as a ratio.
    row = _row("51125", "481400", "100", "150", "8490", "2409", "1963")
    out = _parse_acs_row(_HEADER, row)
    assert "owner_occupied_pct" not in out


def test_sane_rejects_out_of_range_income():
    assert _sane("50000000", 1_000, 500_000) is None  # implausible income
    assert _sane("51125", 1_000, 500_000) == 51125.0


def test_enrich_skips_listing_that_already_has_demographics(monkeypatch):
    li = Listing(source="x", source_url="u1", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Buncombe", zip_code="28801",
                 raw={"census_demographics": {"median_household_income": 1}})
    stats = enrich_census_demographics([li])
    assert stats["filled"] == 0
    assert li.raw["census_demographics"] == {"median_household_income": 1}


def test_enrich_fills_from_cache_without_network(monkeypatch):
    _zip_cache.clear()
    _zip_cache["28801"] = {
        "median_household_income": 51125, "median_home_value": 481400,
        "owner_occupied_pct": 36.7, "vacant_housing_pct": 28.4,
        "median_year_built": 1963,
    }
    li = Listing(source="x", source_url="u2", listing_type=ListingType.FORECLOSURE_SALE,
                 state="NC", county="Buncombe", zip_code="28801", raw={})
    stats = enrich_census_demographics([li])
    assert stats["filled"] == 1
    assert li.raw["census_demographics"]["median_household_income"] == 51125
    assert li.raw["census_demographics"]["zcta5"] == "28801"
    assert li.raw["census_demographics"]["source"] == "acs_2023_5yr"
    _zip_cache.clear()
