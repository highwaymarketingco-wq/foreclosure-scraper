"""Mecklenburg County NC tax-foreclosure pipeline (TaxForeclosures layer).

Hand-written fixtures: parcel ids, streets and amounts are made up. Field names
and value shapes follow the live layer as read on 2026-10-07 (lat/lng as strings,
attorney codes KANIA / RBCWB / INREM / UNASSIGNED, 'N/A' legal descriptions).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_nc import mecklenburg_tax_foreclosures as mod
from foreclosure_scraper.web_artifact import RAW_KEEP

from tests._arcgis_fakes import FakeHttp

NOW = mod.datetime(2026, 10, 7)

KANIA_ROW = {
    "objectid": 1, "parcel_id": "99900101", "gis_parcel_id": "99900101",
    "situs": "100  SAMPLE BROOK DR", "property_description": "L7 M99-123",
    "due_amount": 5432.1, "bill_count": 4, "status": None, "zip": "28269",
    "po_name": "CHARLOTTE", "nme_juris": "CHAR", "amt_totalvalue": 210000,
    "num_bedrooms": 3, "cnt_fullbaths": 2, "cnt_halfbaths": 1,
    "cde_propertyuse": "01", "attorney": "KANIA", "proptype": "Residential",
    "units": 1, "latitude": "35.30001", "longitude": "-80.80002",
    "doc_path": None, "bpo_status": None,
    "owner_dob": "01/01/1900",  # must be dropped before anything is stored
}

UNASSIGNED_COMMERCIAL = {
    "objectid": 2, "parcel_id": "99900202", "situs": "9 FICTION PARK RD",
    "property_description": "N/A", "due_amount": 812.0, "bill_count": 1,
    "zip": "28078", "po_name": "HUNTERSVILLE", "attorney": "UNASSIGNED",
    "proptype": "Commercial", "latitude": "not a number", "longitude": None,
}

NO_PARCEL = {"objectid": 3, "parcel_id": None, "gis_parcel_id": "", "situs": "1 NOWHERE"}


def test_kania_row_maps_to_a_tax_lien_with_amount_and_attorney():
    li = mod.build_listing(KANIA_ROW, now=NOW)
    assert li.listing_type == ListingType.TAX_LIEN
    assert li.foreclosure_process == "tax"
    assert li.parcel_id == "99900101"
    assert li.street_address == "100 SAMPLE BROOK DR"
    assert li.city == "CHARLOTTE" and li.zip_code == "28269"
    assert li.county == "Mecklenburg" and li.state == "NC"
    assert li.property_kind == PropertyKind.SINGLE_FAMILY
    assert li.bathrooms == 2.5 and li.bedrooms == 3
    assert abs(li.latitude - 35.30001) < 1e-9
    assert li.owner_name is None, "this layer carries no owner; the resolver adds it"
    block = li.raw["mecklenburg_tax_foreclosure"]
    assert block["total_due"] == 5432.1 and block["bill_count"] == 4
    assert block["attorney"] == "KANIA" and block["attorney_name"] == "Kania Law Firm"
    assert block["legal_description"] == "L7 M99-123"
    assert "$5,432 due over 4 bill(s)" in li.description


def test_bad_coordinates_and_na_legal_are_blanked():
    li = mod.build_listing(UNASSIGNED_COMMERCIAL, now=NOW)
    assert li.latitude is None and li.longitude is None
    assert li.legal_description is None
    assert li.property_kind == PropertyKind.COMMERCIAL
    assert li.raw["mecklenburg_tax_foreclosure"]["attorney_name"].startswith("flagged")


def test_row_without_parcel_is_dropped():
    assert mod.build_listing(NO_PARCEL, now=NOW) is None


def test_sensitive_columns_never_reach_raw():
    li = mod.build_listing(KANIA_ROW, now=NOW)
    assert "01/01/1900" not in repr(li.raw)


def test_raw_block_survives_board_publication_and_fields_are_enumerated():
    assert "mecklenburg_tax_foreclosure" in RAW_KEEP
    assert "*" not in mod.OUT_FIELDS


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def test_fetch_pages_until_the_server_says_done(monkeypatch):
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    first = {"objectIdFieldName": "objectid", "exceededTransferLimit": True,
             "features": [{"attributes": KANIA_ROW}, {"attributes": NO_PARCEL}]}
    second = {"objectIdFieldName": "objectid", "exceededTransferLimit": False,
              "features": [{"attributes": UNASSIGNED_COMMERCIAL}]}
    http = FakeHttp({}, pages=[first, second])
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    rows = asyncio.run(mod.MecklenburgTaxForeclosures().fetch())
    assert [li.parcel_id for li in rows] == ["99900101", "99900202"]
    offsets = [c[2]["resultOffset"] for c in http.calls]
    assert offsets == ["0", "2"]
