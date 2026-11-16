"""Spartanburg County SC homestead exemption scraper. Fixture shape mirrors the real live
attributes (captured 2026-11-16 against the actual ArcGIS CAMA_Parcels layer). No existing
test file covered this scraper before now (round 8 built it 2026-11-16 but never added one);
written while landing its first real catch-up run against the live board
(scripts/run_scoped_scrapers.py --slugs counties_sc.spartanburg_homestead --apply)."""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_sc import spartanburg_homestead as m

from tests._arcgis_fakes import FakeHttp

ROW_GOOD = {
    "GISParcelNumber": "7-18-02-017.00", "MAPNUMBER": "7-18-02-017.00",
    "OwnerName": "SMITH JOHN R", "TaxpayerName": "", "StreetAddress": "123 MAIN ST",
    "City": "SPARTANBURG", "State": "SC", "Zip": "29301",
    "CurrentAppraisedLandValue": "40000", "CurrentAppraisedBuildingValue": "142400",
    "CurrentAssessedLandValue": "1600", "CurrentAssessedBuildingValue": "5696",
    "LandUse": "RESIDENTIAL IMPROVED", "Acreage": 0.42,
    "SaleDate": None, "SaleAmount": None, "AssessmentCode": "4% LEGAL RES",
    "HomesteadNumber": "H",
}
ROW_BLANK_GISPARCEL = {
    "GISParcelNumber": "", "MAPNUMBER": "7-18-02-018.00",
    "OwnerName": "DOE JANE", "TaxpayerName": "", "StreetAddress": "45 OAK LN",
    "City": "Spartanburg", "State": "SC", "Zip": "29301",
    "CurrentAppraisedLandValue": "30000", "CurrentAppraisedBuildingValue": "120000",
    "CurrentAssessedLandValue": "1200", "CurrentAssessedBuildingValue": "4800",
    "LandUse": "RESIDENTIAL IMPROVED", "Acreage": 0.3,
    "SaleDate": 1577836800000, "SaleAmount": "185000", "AssessmentCode": "4% LEGAL RES",
    "HomesteadNumber": "H",
}
ROW_NO_OWNER = {
    "GISParcelNumber": "9999999999", "MAPNUMBER": "9999999999",
    "OwnerName": "", "TaxpayerName": "", "StreetAddress": "1 NOWHERE RD",
    "LandUse": "", "HomesteadNumber": "H",
}
ROW_NO_PARCEL = {
    "GISParcelNumber": "", "MAPNUMBER": "",
    "OwnerName": "NOBODY NOPARCEL", "StreetAddress": "2 NOWHERE RD",
    "LandUse": "", "HomesteadNumber": "H",
}


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _run_fetch(pages: list[dict]) -> list:
    http = FakeHttp(pages=pages)
    s = m.SpartanburgHomestead()
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(s.fetch())
    finally:
        m.client = original


def test_a_good_row_maps_into_a_complete_elderly_disabled_listing():
    out = _run_fetch([{"features": [{"attributes": ROW_GOOD}]}, {"features": []}])
    assert len(out) == 1
    li = out[0]
    assert li.listing_type.value == "elderly_disabled"
    assert li.state == "SC" and li.county == "Spartanburg"
    assert li.parcel_id == "7-18-02-017.00"
    assert li.owner_name == "SMITH JOHN R"
    assert li.street_address == "123 MAIN ST"
    assert li.city == "Spartanburg"
    assert li.property_kind.value == "single_family"
    # market_value reads Appraised (fair market); assessed_value reads Assessed
    # (the smaller, tax-bill-facing ratio value) -- per the scraper's own docstring.
    assert li.market_value == 40000.0 + 142400.0
    assert li.assessed_value == 1600.0 + 5696.0
    assert li.acreage == 0.42


def test_tax_relief_shape_matches_enrichment_tax_relief_homestead_classify_path():
    """distress_score._collect's senior_exemption signal reads raw['tax_relief'] by this
    exact {kind, basis} shape -- a drift here silently stops scoring."""
    out = _run_fetch([{"features": [{"attributes": ROW_GOOD}]}, {"features": []}])
    assert out[0].raw["tax_relief"] == {
        "kind": "homestead_exemption", "basis": "sc_homestead_age65_disabled",
        "deferred_value": None, "county": "Spartanburg",
    }


def test_gis_exempt_carries_the_homestead_code_and_assessment_code():
    out = _run_fetch([{"features": [{"attributes": ROW_GOOD}]}, {"features": []}])
    assert out[0].raw["gis_exempt"] == {
        "code": "H", "tag": "sc_homestead_exemption", "assessment_code": "4% LEGAL RES",
    }


def test_no_owner_mailing_is_constructed_unlike_york_lexington():
    """This layer has no separate mailing-address columns -- per the scraper's own
    docstring, raw['owner_mailing'] must never appear (fabricating one from the situs
    fields would misleadingly imply an independently-sourced second address)."""
    out = _run_fetch([{"features": [{"attributes": ROW_GOOD}]}, {"features": []}])
    assert "owner_mailing" not in out[0].raw


def test_gisparcelnumber_blank_falls_back_to_mapnumber():
    out = _run_fetch([{"features": [{"attributes": ROW_BLANK_GISPARCEL}]}, {"features": []}])
    assert len(out) == 1
    assert out[0].parcel_id == "7-18-02-018.00"


def test_a_real_sale_populates_raw_gis_last_sale():
    out = _run_fetch([{"features": [{"attributes": ROW_BLANK_GISPARCEL}]}, {"features": []}])
    sale = out[0].raw["gis"]["last_sale"]
    assert sale["amount"] == 185000.0
    assert sale["date"] == "2020-01-01"
    assert sale["source"] == "spartanburg_homestead_gis"


def test_row_with_no_owner_is_skipped():
    out = _run_fetch([{"features": [{"attributes": ROW_NO_OWNER}]}, {"features": []}])
    assert out == []


def test_row_with_no_usable_parcel_id_is_skipped():
    out = _run_fetch([{"features": [{"attributes": ROW_NO_PARCEL}]}, {"features": []}])
    assert out == []


def test_pagination_follows_offset_across_a_full_page():
    full_page = [{"attributes": {**ROW_GOOD, "GISParcelNumber": f"PARCEL{i:04d}",
                                  "MAPNUMBER": f"PARCEL{i:04d}", "OwnerName": f"OWNER {i}"}}
                 for i in range(m._PAGE)]
    out = _run_fetch([{"features": full_page},
                      {"features": [{"attributes": ROW_BLANK_GISPARCEL}]},
                      {"features": []}])
    assert len(out) == m._PAGE + 1


def test_http_failure_yields_nothing_not_a_crash():
    http = FakeHttp(routes={})  # no pages queued, no matching route -> error payload
    s = m.SpartanburgHomestead()
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        out = asyncio.run(s.fetch())
    finally:
        m.client = original
    assert out == []


def test_gate_env_var_skips_the_source(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_SPARTANBURG_HOMESTEAD_SOURCE", "0")
    out = asyncio.run(m.SpartanburgHomestead().fetch())
    assert out == []
