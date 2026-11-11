"""York County SC homestead exemption scraper. Fixture shape mirrors the real
live attributes (captured 2026-11-11 against the actual ArcGIS layer); owners/
parcels changed."""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_sc import york_homestead as m

from tests._arcgis_fakes import FakeHttp

ROW_GOOD = {
    "ParcelID": "0101001122", "TAXMAPID": "0101001122", "Owner1": "SMITH JOHN R",
    "Owner2": "SMITH MARY E", "Owner3": "", "PropertyAddress": "123 MAIN ST",
    "MailAddr1": "123 MAIN ST", "MailAddr2": "", "MailCity": "ROCK HILL",
    "MailState": "SC", "MailZip": "29730", "AprTotVal": "182400", "TaxTotVal": "91200",
    "LandUseDesc": "RESIDENTIAL IMPROVED OC", "deededacres": 0.42, "HOMESTEAD": "Y",
}
ROW_OUT_OF_STATE_MAILING = {
    "ParcelID": "5410000087", "TAXMAPID": "5410000087", "Owner1": "DOE JANE",
    "Owner2": "", "Owner3": "", "PropertyAddress": "45 OAK LN",
    "MailAddr1": "99 PINE AVE", "MailAddr2": "", "MailCity": "CHARLOTTE",
    "MailState": "NC", "MailZip": "28202", "AprTotVal": "210000", "TaxTotVal": "105000",
    "LandUseDesc": "RESIDENTIAL IMPROVED OC", "deededacres": 0.3, "HOMESTEAD": "Y",
}
ROW_NO_OWNER = {
    "ParcelID": "9999999999", "Owner1": "", "Owner2": "", "Owner3": "",
    "PropertyAddress": "1 NOWHERE RD", "HOMESTEAD": "Y",
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
    s = m.YorkHomestead()
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
    assert li.state == "SC" and li.county == "York"
    assert li.parcel_id == "0101001122"
    assert li.owner_name == "SMITH JOHN R; SMITH MARY E"
    assert li.street_address == "123 MAIN ST"
    assert li.market_value == 182400.0
    assert li.assessed_value == 91200.0
    assert li.acreage == 0.42


def test_tax_relief_shape_matches_enrichment_tax_relief_york_sc_classify_path():
    """distress_score._collect's senior_exemption signal reads raw['tax_relief']
    by this exact {kind, basis} shape -- a drift here silently stops scoring."""
    out = _run_fetch([{"features": [{"attributes": ROW_GOOD}]}, {"features": []}])
    assert out[0].raw["tax_relief"] == {
        "kind": "homestead_exemption", "basis": "sc_homestead_age65_disabled",
        "deferred_value": None, "county": "York",
    }


def test_out_of_state_mailing_is_flagged_absentee_and_out_of_state():
    out = _run_fetch([{"features": [{"attributes": ROW_OUT_OF_STATE_MAILING}]}, {"features": []}])
    om = out[0].raw["owner_mailing"]
    assert om["out_of_state"] is True
    assert om["absentee"] is True
    assert om["mail_state"] == "NC"


def test_row_with_no_owner_is_skipped():
    out = _run_fetch([{"features": [{"attributes": ROW_NO_OWNER}]}, {"features": []}])
    assert out == []


def test_pagination_follows_offset_across_a_full_page():
    full_page = [{"attributes": {**ROW_GOOD, "ParcelID": f"PARCEL{i:04d}",
                                  "Owner1": f"OWNER {i}"}} for i in range(m._PAGE)]
    out = _run_fetch([{"features": full_page}, {"features": [{"attributes": ROW_OUT_OF_STATE_MAILING}]},
                      {"features": []}])
    assert len(out) == m._PAGE + 1


def test_http_failure_yields_nothing_not_a_crash():
    http = FakeHttp(routes={})  # no pages queued, no matching route -> error payload
    s = m.YorkHomestead()
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        out = asyncio.run(s.fetch())
    finally:
        m.client = original
    assert out == []


def test_gate_env_var_skips_the_source(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_YORK_HOMESTEAD_SOURCE", "0")
    out = asyncio.run(m.YorkHomestead().fetch())
    assert out == []
