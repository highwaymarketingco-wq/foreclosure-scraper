"""Buncombe County NC elderly/disabled homeowners (property-tax exemption roll).

EXTRACTION-COMPLETENESS AUDIT 2026-10-03: the SAME bulk ArcGIS query (no extra
request) also carries SalePrice/DeedDate/DeedBook/DeedPage/Instrument (a real
recorded last-sale, live-confirmed on 1,627/4,352 rows) and CareOf (an
executor/relative mailing name, live-confirmed on several rows) that this
scraper never read at all. Fixture shape mirrors the real live attributes
(captured 2026-10-03); PINs/owners/amounts changed.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_nc import buncombe_elderly as m

from tests._arcgis_fakes import FakeHttp

ROW_WITH_SALE = {
    "pin": "9627320743", "owner": "MARTIN JASON V;LECHNER TERRI",
    "Address": "19 MORSE DR", "CityName": "ASHEVILLE", "State": "NC", "Zipcode": "28806",
    "TotalMarketValue": "286300", "TaxValue": "286300", "LandUse": "", "Class": "100",
    "Acreage": 0.36, "Exempt": "VET", "CareOf": "",
    "SalePrice": 180000.0, "DeedDate": "20070814", "DeedBook": "4449", "DeedPage": "1243",
    "Instrument": "WDT",
}
ROW_WITH_CARE_OF_NO_SALE = {
    "pin": "9649292284", "owner": "MCAFEE PATRICIA A",
    "Address": "21 LAUREL AVE", "CityName": "ASHEVILLE", "State": "NC", "Zipcode": "28804",
    "TotalMarketValue": "332800", "TaxValue": "332800", "LandUse": "", "Class": "100",
    "Acreage": 0.23, "Exempt": "ELD", "CareOf": "LYNN REED",
    "SalePrice": 0.0, "DeedDate": "19851218", "DeedBook": "1413", "DeedPage": "0681",
    "Instrument": "DEE",
}
ROW_NO_SALE_NO_CARE_OF = {
    "pin": "9668461065", "owner": "BELLOWS JOAN H",
    "Address": "22 BROWNDALE RD", "CityName": "ASHEVILLE", "State": "NC", "Zipcode": "28805",
    "TotalMarketValue": "187300", "TaxValue": "187300", "LandUse": "", "Class": "100",
    "Acreage": 0.22, "Exempt": "ELD", "CareOf": "",
    "SalePrice": None, "DeedDate": "", "DeedBook": "", "DeedPage": "", "Instrument": "",
}


def _run_fetch(features: list[dict]) -> list:
    http = FakeHttp(pages=[{"features": features}, {"features": []}])
    s = m.BuncombeElderly()
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(s.fetch())
    finally:
        m.client = original


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def test_iso_date_parses_the_8digit_deeddate():
    assert m._iso_date("20070814") == "2007-08-14"
    assert m._iso_date(19851218) == "1985-12-18"
    assert m._iso_date("") is None
    assert m._iso_date("not-a-date") is None
    assert m._iso_date("99999999") is None  # not a real calendar date


def test_a_real_sale_is_surfaced_into_raw_gis_last_sale():
    out = _run_fetch([{"attributes": ROW_WITH_SALE}])
    assert len(out) == 1
    li = out[0]
    assert li.raw["gis"]["last_sale"] == {
        "date": "2007-08-14", "amount": 180000.0, "source": "buncombe_elderly_gis",
        "deed_book": "4449", "deed_page": "1243", "instrument": "WDT",
    }


def test_a_zero_sale_price_is_not_surfaced_as_a_free_property():
    """SalePrice 0 means no arms-length sale was recorded (inheritance, a
    correction deed, etc) -- NOT a $0 purchase; must not be labelled a sale."""
    out = _run_fetch([{"attributes": ROW_WITH_CARE_OF_NO_SALE}])
    assert "gis" not in out[0].raw


def test_care_of_is_surfaced_only_when_present():
    out = _run_fetch([{"attributes": ROW_WITH_CARE_OF_NO_SALE}, {"attributes": ROW_NO_SALE_NO_CARE_OF}])
    with_careof = next(l for l in out if l.owner_name == "MCAFEE PATRICIA A")
    no_careof = next(l for l in out if l.owner_name == "BELLOWS JOAN H")
    assert with_careof.raw["gis_exempt"]["care_of"] == "LYNN REED"
    assert "care_of" not in no_careof.raw["gis_exempt"]
    assert "gis" not in no_careof.raw


def test_registered_in_the_scraper_registry():
    from foreclosure_scraper.scrapers._registry import discover
    slugs = {c.slug for c in discover()}
    assert m.BuncombeElderly.slug in slugs


# --- 2026-10-07 extraction audit: property-card columns never requested. Values made up. ---

ROW_CARD = {
    "pin": "9600000001", "owner": "SAMPLE PAT", "Address": "1 TEST LN", "CityName": "ASHEVILLE",
    "State": "NC", "Zipcode": "28801", "TotalMarketValue": "200000", "TaxValue": "200000",
    "Class": "100", "Exempt": "ELD",
    "propcard": "https://example.invalid/propcard?pin=9600000001",
    "LandValue": "50000", "BuildingValue": "150000", "AppraisedValue": "200000",
    "ImprovementValue": "", "SubName": "TEST ACRES", "SubLot": "12", "SubBlock": "B",
    "SubSect": "", "PlatBook": "0099", "PlatPage": "0042", "Stamps": 300.0, "Reason": "Q",
    "Improved": "Y", "NeighborhoodCode": "N1", "Township": "AS",
}


def test_card_columns_are_requested():
    for col in ("propcard", "LandValue", "BuildingValue", "AppraisedValue", "SubName",
                "SubLot", "PlatBook", "PlatPage", "Stamps"):
        assert col in m._OUT.split(","), col


def test_card_facts_land_in_gis_exempt():
    li = _run_fetch([{"attributes": ROW_CARD}])[0]
    g = li.raw["gis_exempt"]
    assert g["propcard"].startswith("https://")
    assert g["land_value"] == 50000.0 and g["building_value"] == 150000.0
    assert g["appraised_value"] == 200000.0
    assert (g["subdivision"], g["sub_lot"], g["sub_block"]) == ("TEST ACRES", "12", "B")
    assert (g["plat_book"], g["plat_page"]) == ("0099", "0042")
    assert g["deed_stamps"] == 300.0 and g["sale_reason"] == "Q" and g["improved"] == "Y"
    assert "improvement_value" not in g and "sub_section" not in g   # empty -> absent


def test_rows_without_card_columns_gain_no_keys():
    li = _run_fetch([{"attributes": ROW_NO_SALE_NO_CARE_OF}])[0]
    assert set(li.raw["gis_exempt"]) == {"code", "tag"}
