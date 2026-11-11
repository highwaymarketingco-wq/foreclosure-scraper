"""Lexington County SC homestead exemption scraper. Fixture shape mirrors the
real live attributes (captured 2026-11-11 against the actual ArcGIS layer);
owners/parcels changed."""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_sc import lexington_homestead as m

from tests._arcgis_fakes import FakeHttp

ROW_GOOD = {
    "TMS": "005722-06-010", "TMS_No_Dash": "0057220610", "Owner": "RICHARDS JONI K",
    "PropAddr_Num": "212", "PropAddr_Str": "CEDAR CREEK", "PropAddr_Suf": "RD",
    "PropAddr_City": "LEXINGTON", "PropAddr_State": "SC", "PropAddr_Zip": "29072",
    "MailAddr": "212 CEDAR CREEK RD", "MailAddr2": "", "MailAddr3": "",
    "MailAddr_City": "LEXINGTON", "MailAddr_State": "SC", "MailAddr_Zip": "29072",
    "MktTotal": "245600", "TaxableTotal": "98240", "Acres": 0.55,
    "PropTypeDesc": "RESIDENTIAL", "Homestead": "YES",
}
ROW_OUT_OF_STATE_MAILING = {
    "TMS": "005732-07-020", "TMS_No_Dash": "0057320720", "Owner": "BRATCHER JANET",
    "PropAddr_Num": "88", "PropAddr_Str": "ELM", "PropAddr_Suf": "DR",
    "PropAddr_City": "LEXINGTON", "PropAddr_State": "SC", "PropAddr_Zip": "29072",
    "MailAddr": "PO BOX 44", "MailAddr2": "", "MailAddr3": "",
    "MailAddr_City": "ATLANTA", "MailAddr_State": "GA", "MailAddr_Zip": "30301",
    "MktTotal": "190000", "TaxableTotal": "76000", "Acres": 0.4,
    "PropTypeDesc": "RESIDENTIAL", "Homestead": "YES",
}
ROW_NO_OWNER = {
    "TMS": "", "TMS_No_Dash": "", "Owner": "", "PropAddr_Num": "1",
    "PropAddr_Str": "NOWHERE", "PropAddr_Suf": "RD", "Homestead": "YES",
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
    s = m.LexingtonHomestead()
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(s.fetch())
    finally:
        m.client = original


def test_a_good_row_maps_into_a_complete_elderly_disabled_listing_with_city_zip():
    out = _run_fetch([{"features": [{"attributes": ROW_GOOD}]}, {"features": []}])
    assert len(out) == 1
    li = out[0]
    assert li.listing_type.value == "elderly_disabled"
    assert li.state == "SC" and li.county == "Lexington"
    assert li.parcel_id == "005722-06-010"
    assert li.street_address == "212 CEDAR CREEK RD"
    assert li.city == "Lexington"
    assert li.zip_code == "29072"
    assert li.market_value == 245600.0
    assert li.assessed_value == 98240.0


def test_tax_relief_shape_matches_enrichment_tax_relief_lexington_sc_classify_path():
    out = _run_fetch([{"features": [{"attributes": ROW_GOOD}]}, {"features": []}])
    assert out[0].raw["tax_relief"] == {
        "kind": "homestead_exemption", "basis": "sc_homestead_age65_disabled",
        "deferred_value": None, "county": "Lexington",
    }


def test_out_of_state_mailing_is_flagged_absentee_and_out_of_state():
    out = _run_fetch([{"features": [{"attributes": ROW_OUT_OF_STATE_MAILING}]}, {"features": []}])
    om = out[0].raw["owner_mailing"]
    assert om["out_of_state"] is True
    assert om["absentee"] is True
    assert om["mail_state"] == "GA"


def test_row_with_no_owner_or_tms_is_skipped():
    out = _run_fetch([{"features": [{"attributes": ROW_NO_OWNER}]}, {"features": []}])
    assert out == []


def test_pagination_follows_offset_across_a_full_page():
    full_page = [{"attributes": {**ROW_GOOD, "TMS": f"TMS-{i:04d}",
                                  "Owner": f"OWNER {i}"}} for i in range(m._PAGE)]
    out = _run_fetch([{"features": full_page}, {"features": [{"attributes": ROW_OUT_OF_STATE_MAILING}]},
                      {"features": []}])
    assert len(out) == m._PAGE + 1


def test_http_failure_yields_nothing_not_a_crash():
    http = FakeHttp(routes={})
    s = m.LexingtonHomestead()
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        out = asyncio.run(s.fetch())
    finally:
        m.client = original
    assert out == []


def test_gate_env_var_skips_the_source(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_LEXINGTON_HOMESTEAD_SOURCE", "0")
    out = asyncio.run(m.LexingtonHomestead().fetch())
    assert out == []
