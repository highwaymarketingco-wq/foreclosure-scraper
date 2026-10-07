"""Guilford County NC tax-foreclosure pipeline (ForeclosuresPublic layer).

Fixtures are hand-written: every name, street and number below is made up. The
field names and value shapes match the live layer as read on 2026-10-07 (epoch-ms
dates, WGS84 centroids, padded FLAG_TYPE, 10-digit PIN).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_nc import guilford_tax_foreclosures as mod
from foreclosure_scraper.web_artifact import RAW_KEEP

from tests._arcgis_fakes import FakeHttp

NOW = mod.datetime(2026, 10, 7)

UPSET_BID = {
    "OBJECTID": 11,
    "Owner": "TESTPERSON, ALEXANDRA Q",
    "LOCATION_ADDR": "123 EXAMPLE MEADOW LN",
    "Total_Assessed": 41000.0,
    "YEAR_BUILT": 1958,
    "PARCEL_ID": "900001",
    "REID": "900001",
    "PIN": "7899000001",
    "FLAG_TYPE": "FLAGMORTGAGE                                      ",
    "FLAG_STATUS": "Upset Bid",
    "Centroid_X": -79.80123,
    "Centroid_Y": 36.05123,
    "AuctionDate": 1790035200000,  # 2026-09-22 UTC
    "AuctionTime": "12 Noon",
    "AuctionLocation": "Greensboro Courthouse 201 S Eugene St, Greensboro, NC 27401",
    "Mail_Address": "PO BOX 9999",
    "Mail_City": "SAMPLEVILLE",
    "Mail_State": "VA",
    "Mail_Zip": "22000",
    "PROPERTY_DESCR": "LOT 4 PB 99-999 EXAMPLE MEADOW",
    "Deed": "009999-00123",
    "Plat": "99-999",
    "DEED_DATE": 1154923260000,
    "Property_Type": "RESIDENTIAL",
    "Structure_Size": 980,
    "Lot_Size": 0.21,
    "BEDROOMS": 2,
    "Bathrooms": 1,
    # A column a county could add one day; it must never reach the lead.
    "TAXPAYER_SSN": "000-00-0000",
}

ASSIGNED = {
    "OBJECTID": 12,
    "Owner": "SAMPLE HOLDINGS LLC",
    "LOCATION_ADDR": "45 FICTION ST",
    "Total_Assessed": 7000.0,
    "PARCEL_ID": "900002",
    "REID": "900002",
    "PIN": "7899000002",
    "FLAG_TYPE": "FLAGMORTGAGE",
    "FLAG_STATUS": "Assigned To Attorney",
    "Centroid_X": -79.9,
    "Centroid_Y": 36.0,
    "AuctionDate": None,
    "Mail_Address": "45 FICTION ST",
    "Mail_City": "GREENSBORO",
    "Mail_State": "NC",
    "Mail_Zip": "27401",
    "Property_Type": "VACANT",
}

NO_ID = {"OBJECTID": 13, "Owner": "NOBODY", "LOCATION_ADDR": "1 NOWHERE RD",
         "FLAG_STATUS": "Assigned To Attorney"}


def test_upset_bid_row_is_a_dated_tax_sale_with_owner_and_mailing():
    li = mod.build_listing(UPSET_BID, now=NOW)
    assert li is not None
    assert li.listing_type == ListingType.TAX_SALE
    assert li.county == "Guilford" and li.state == "NC"
    assert li.parcel_id == "7899000001"
    assert li.owner_name == "TESTPERSON, ALEXANDRA Q" == li.defendant
    assert li.street_address == "123 EXAMPLE MEADOW LN"
    assert li.sale_date is not None and li.sale_date.date().isoformat() == "2026-09-22"
    assert li.auction_status == "Upset Bid"
    assert li.foreclosure_process == "tax"
    assert li.property_kind == PropertyKind.SINGLE_FAMILY
    assert abs(li.latitude - 36.05123) < 1e-6 and abs(li.longitude + 79.80123) < 1e-6
    block = li.raw["guilford_tax_foreclosure"]
    assert block["flag_type"] == "FLAGMORTGAGE"
    assert block["deed"] == "009999-00123"
    assert block["auction_date_past"] is True
    mail = li.raw["owner_mailing"]
    assert mail["out_of_state"] is True and mail["absentee"] is True
    assert mail["mail_state"] == "VA"


def test_assigned_to_attorney_is_a_pre_sale_tax_lien_without_sale_fields():
    li = mod.build_listing(ASSIGNED, now=NOW)
    assert li.listing_type == ListingType.TAX_LIEN
    assert li.sale_date is None and li.sale_location is None
    assert li.property_kind == PropertyKind.LAND
    assert li.raw["owner_mailing"]["absentee"] is False


def test_row_without_pin_or_parcel_is_dropped():
    assert mod.build_listing(NO_ID, now=NOW) is None


def test_sensitive_columns_never_reach_raw():
    li = mod.build_listing(UPSET_BID, now=NOW)
    flat = repr(li.raw)
    assert "000-00-0000" not in flat and "SSN" not in flat


def test_out_fields_are_enumerated_and_skip_prior_owner_history():
    assert "*" not in mod.OUT_FIELDS
    assert "Owner_History" not in mod.OUT_FIELDS
    assert "OBJECTID" in mod.OUT_FIELDS.split(",")


def test_raw_block_survives_board_publication():
    assert "guilford_tax_foreclosure" in RAW_KEEP


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def test_fetch_reads_the_layer_and_maps_every_row(monkeypatch):
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    page = {"objectIdFieldName": "OBJECTID", "exceededTransferLimit": False,
            "features": [{"attributes": UPSET_BID}, {"attributes": ASSIGNED},
                         {"attributes": NO_ID}]}
    http = FakeHttp({}, pages=[page])
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    rows = asyncio.run(mod.GuilfordTaxForeclosures().fetch())
    assert [li.parcel_id for li in rows] == ["7899000001", "7899000002"]
    verb, url, params = http.calls[0]
    assert url.endswith("ForeclosuresPublic/FeatureServer/0/query")
    assert params["outFields"] == mod.OUT_FIELDS and params["where"] == "1=1"


def test_env_gate_skips_without_a_request(monkeypatch):
    monkeypatch.setenv(mod.ENV_OFF, "0")
    http = FakeHttp({})
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    assert asyncio.run(mod.GuilfordTaxForeclosures().fetch()) == []
    assert http.calls == []
