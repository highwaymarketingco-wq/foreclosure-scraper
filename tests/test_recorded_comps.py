"""Recorded-sales comp engine: per-county filter syntax, ppsf math, and the
Tier-0 precedence in the ARV calculator (recorded sales beat scraped listings)."""
from __future__ import annotations

from foreclosure_scraper import enrichment_recorded_comps as rc
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.valuation import calc


def test_date_clause_per_kind():
    assert rc._date_clause(rc.RECORDED_COMP_CONFIG[("NC", "Gaston")]) == "SALEDATE > DATE '2023-01-01'"
    assert rc._date_clause(rc.RECORDED_COMP_CONFIG[("NC", "Lincoln")]) == "DEEDYR >= 2023"
    assert rc._date_clause(rc.RECORDED_COMP_CONFIG[("NC", "Transylvania")]) == "SALE_DATE >= '202301'"
    assert rc._date_clause(rc.RECORDED_COMP_CONFIG[("SC", "Laurens")]) == "Sale_Date >= '20230101'"


def test_where_includes_arms_length_and_sqft():
    w = rc._where(rc.RECORDED_COMP_CONFIG[("NC", "Gaston")])
    assert "SALESAMT > 10000" in w and "SQFT > 200" in w and "DATE '2023-01-01'" in w


def test_where_skips_sqft_when_absent():
    w = rc._where(rc.RECORDED_COMP_CONFIG[("SC", "Spartanburg")])
    assert "SaleAmount > 10000" in w
    assert "sqft" not in w.lower()


def test_ppsf_list_filters_garbage():
    cfg = rc.RECORDED_COMP_CONFIG[("NC", "Gaston")]
    feats = [
        {"attributes": {"SALESAMT": 300000, "SQFT": 1500}},   # 200 ok
        {"attributes": {"SALESAMT": 1, "SQFT": 1500}},        # nominal -> drop
        {"attributes": {"SALESAMT": 300000, "SQFT": 10}},     # tiny sqft -> drop
        {"attributes": {"SALESAMT": 5_000_000, "SQFT": 500}}, # 10000 $/sqft -> drop (ceil)
        {"attributes": {"SALESAMT": 150000, "SQFT": 1500}},   # 100 ok
    ]
    assert rc._ppsf_list(feats, cfg) == [100.0, 200.0]


def test_ppsf_list_empty_without_sqft_field():
    cfg = rc.RECORDED_COMP_CONFIG[("SC", "Spartanburg")]   # sqft=None
    assert rc._ppsf_list([{"attributes": {"SaleAmount": 200000}}], cfg) == []


def test_percentile():
    assert rc._percentile([10, 20, 30, 40], 0.25) == 20
    assert rc._percentile([], 0.5) == 0.0


def test_recorded_comps_beat_scraped_in_calc():
    # Both recorded + scraped present -> recorded (Tier 0) wins.
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO,
                 state="NC", county="Gaston", living_sqft=1500, tax_value=200000,
                 raw={"comp_median_ppsf_recorded": 180.0,
                      "recorded_comps": {"median_ppsf": 180.0, "count": 12,
                                         "p25_ppsf": 150.0, "p75_ppsf": 210.0,
                                         "radius_mi": 1.0, "confidence": "HIGH"},
                      "comps": [{"price_per_sqft": 999}] * 3,
                      "comp_median_ppsf": 999})
    c = calc.compute(li)
    assert c.arv_expected == 270000          # 180 * 1500, NOT 999*1500
    assert c.arv_confidence == "HIGH"
    assert any("RECORDED arms-length" in n for n in c.notes)


def test_recorded_low_count_is_medium():
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO,
                 state="NC", county="Gaston", living_sqft=1000,
                 raw={"comp_median_ppsf_recorded": 150.0,
                      "recorded_comps": {"median_ppsf": 150.0, "count": 3,
                                         "p25_ppsf": 140.0, "p75_ppsf": 160.0,
                                         "radius_mi": 1.0, "confidence": "MEDIUM"}})
    c = calc.compute(li)
    assert c.arv_expected == 150000
    assert c.arv_confidence == "MEDIUM"
