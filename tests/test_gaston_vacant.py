"""Gaston County NC vacant-parcels extraction-completeness audit (2026-10-03).

The bulk ArcGIS query already in ``_OUT`` left six real fields on the table,
discovered diffing the live layer schema (MapServer/11?f=json, 89 fields)
against what the scraper requested, then live-sampling 2,000 real rows:

  - ImagePath (58.6% filled) -- an internal UNC share path, NOT a public URL,
    but live-confirmed the county's own DevNet Wedge parcel page serves the
    SAME file publicly at a derived https://gastonnc.devnetwedge.com/
    PropertyImages/... URL (4/4 live samples returned real image/jpeg).
  - LEGDESC_1 (100% filled) -- legal description, never wired to
    Listing.legal_description.
  - DEED_BOOK/DEED_PAGE/DEEDTYPE (100%/100%/98.9% filled) -- recorded-deed
    reference + deed type code.
  - CURR_NAME2/CURR_ADDR2 (21.1%/15.8% filled) -- co-owner name + mailing
    line 2, dropped entirely (only NAME1/ADDR1 were read).

Also: SALEDATE/SALESAMT were already fetched but only stashed under the
private raw.gaston_gis key, which enrichment_last_sale.py never reads (it
reads raw['gis']['last_sale']) -- now surfaced there too (same convention as
the batch-2 Pickens fix and batch-3 Buncombe-elderly fix).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_nc import gaston_vacant as m
from tests._arcgis_fakes import FakeHttp


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _run_fetch(features: list[dict]):
    http = FakeHttp(pages=[{"features": features}])
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(m.GastonVacant().fetch())
    finally:
        m.client = original


# Shape mirrors the real live attributes captured 2026-10-03 (PIN/owner changed).
ROW_FULL = {
    "PIN": "3546-64-4858", "PID": "100051", "WHOLE_ADDRESS": "123 MAIN ST",
    "PHYSSTRADD": "123 MAIN ST", "POSTAL": "GASTONIA", "STATE": "NC", "ZIP": 28052,
    "JAN1_NAME1": "DOE JOHN", "JAN1_NAME2": "DOE JANE",
    "CURR_NAME1": "DOE JOHN", "CURR_NAME2": "DOE JANE",
    "CURR_ADDR1": "456 OTHER ST", "CURR_ADDR2": "APT 2",
    "CURR_CITY": "CHARLOTTE", "CURR_STATE": "NC", "CURR_ZIPCODE": "28202",
    "Latitude": 35.25, "Longitude": -81.18,
    "FMV_TOTAL": 45000.0, "FMV_LAND": 45000.0, "FMV_IMPRV": 0.0, "TOTVAL": 45000.0,
    "SALEDATE": 1358294400000,  # 2013-01-16 (epoch ms)
    "SALESAMT": 32000.0, "SQFT": 0, "YEARBLT": 0,
    "property_use": "VACANT", "DESC1_DESC": "VACANT LOT", "VacantImpro": "Vacant",
    "CALCAC": 0.42, "DEEDAC": 0.42,
    "ImagePath": r"\\GCSQL-DVNT25\DEVNET\Images\ASRIMG\2019\984056.JPG",
    "LEGDESC_1": "WELDON HEIGHTS BLK C L 19 01 001 001 00 000",
    "DEED_BOOK": "5516", "DEED_PAGE": "1376", "DEEDTYPE": "QCD",
}

ROW_SPARSE = {
    **{k: ROW_FULL[k] for k in ("PIN", "PID", "WHOLE_ADDRESS", "POSTAL", "STATE", "ZIP",
                                 "JAN1_NAME1", "CURR_NAME1", "CURR_ADDR1", "CURR_CITY",
                                 "CURR_STATE", "CURR_ZIPCODE", "Latitude", "Longitude",
                                 "FMV_TOTAL", "FMV_LAND", "FMV_IMPRV", "TOTVAL", "SQFT",
                                 "YEARBLT", "property_use", "DESC1_DESC", "VacantImpro",
                                 "CALCAC", "DEEDAC")},
    "PIN": "3546-00-0000",
    "JAN1_NAME2": "", "CURR_NAME2": "", "CURR_ADDR2": "",
    "SALEDATE": None, "SALESAMT": None,
    "ImagePath": "", "LEGDESC_1": "", "DEED_BOOK": "", "DEED_PAGE": "", "DEEDTYPE": "",
}


def test_image_url_derives_public_devnet_path_from_unc_share():
    assert m._image_url(
        r"\\GCSQL-DVNT25\DEVNET\Images\ASRIMG\2019\984056.JPG"
    ) == "https://gastonnc.devnetwedge.com/PropertyImages/ASRIMG/2019/984056.JPG"


def test_image_url_handles_missing_or_unrecognized_path():
    assert m._image_url(None) is None
    assert m._image_url("") is None
    assert m._image_url(r"\\some\other\share\no_images_marker.JPG") is None


def test_full_row_surfaces_photo_legal_desc_deed_ref_and_co_owner():
    out = _run_fetch([{"attributes": ROW_FULL}])
    assert len(out) == 1
    li = out[0]

    assert li.raw["images"]["real"] == [
        "https://gastonnc.devnetwedge.com/PropertyImages/ASRIMG/2019/984056.JPG"
    ]
    assert li.legal_description == "WELDON HEIGHTS BLK C L 19 01 001 001 00 000"
    assert li.raw["gaston_gis"]["deed_book"] == "5516"
    assert li.raw["gaston_gis"]["deed_page"] == "1376"
    assert li.raw["gaston_gis"]["deed_type"] == "QCD"
    assert li.raw["gaston_gis"]["owner_mailing"]["name2"] == "DOE JANE"
    assert li.raw["gaston_gis"]["owner_mailing"]["addr2"] == "APT 2"

    # Canonical shape enrichment_last_sale.py reads.
    assert li.raw["gis"]["last_sale"] == {
        "date": "2013-01-16T00:00:00", "amount": 32000.0, "source": "gaston_gis",
    }


def test_sparse_row_does_not_fabricate_optional_fields():
    out = _run_fetch([{"attributes": ROW_SPARSE}])
    assert len(out) == 1
    li = out[0]
    assert li.legal_description is None
    assert "images" not in li.raw
    assert "gis" not in li.raw
    assert li.raw["gaston_gis"]["deed_book"] is None
    assert li.raw["gaston_gis"]["owner_mailing"]["name2"] is None


# --- 2026-10-07 extraction audit: five more layer columns, and the standard top-level
# owner_mailing block (mailing_shape.mailing_of reads only raw['owner_mailing']). ---

ROW_NEW = {**ROW_FULL, "PIN": "3546-11-1111",
           "CURR_ADDR1": "9 SAMPLE RD", "CURR_ADDR2": "", "CURR_CITY": "SAMPLETOWN",
           "CURR_STATE": "SC", "CURR_ZIPCODE": "29000",
           "DEEDQUAL_CODEDESC": "UNQUALIFIED", "EXEMPT_COD": "EX1",
           "PRVYRNAME1": "EXAMPLE PAT", "PRVYRNAME2": "", "FLOODAREA": "Y"}


def test_new_layer_columns_are_requested():
    for col in ("DEEDQUAL_CODEDESC", "EXEMPT_COD", "PRVYRNAME1", "PRVYRNAME2", "FLOODAREA"):
        assert col in m._OUT.split(","), col


def test_new_columns_land_in_the_raw_block():
    li = _run_fetch([{"attributes": ROW_NEW}])[0]
    g = li.raw["gaston_gis"]
    assert g["deed_qualification"] == "UNQUALIFIED"
    assert g["exempt_code"] == "EX1"
    assert g["prior_year_owner"] == "EXAMPLE PAT" and g["prior_year_owner2"] is None
    assert g["flood_area"] == "Y"
    assert li.raw["gis"]["last_sale"]["qualification"] == "UNQUALIFIED"


def test_standard_owner_mailing_block_is_written_for_the_scorer():
    from foreclosure_scraper.mailing_shape import mailing_of
    li = _run_fetch([{"attributes": ROW_NEW}])[0]
    om = mailing_of(li)
    assert om["mailing"] == "9 SAMPLE RD, SAMPLETOWN SC 29000"
    assert om["mail_state"] == "SC" and om["out_of_state"] is True
    assert om["absentee"] is True
    assert om["parcel_id"] == "3546-11-1111" and om["source"] == "gaston_county_gis"
    assert om["owner"] == "DOE JOHN & DOE JANE"


def test_owner_occupied_parcel_is_not_absentee():
    row = {**ROW_NEW, "CURR_ADDR1": "123 MAIN ST", "CURR_CITY": "GASTONIA",
           "CURR_STATE": "NC", "CURR_ZIPCODE": "28052"}
    om = _run_fetch([{"attributes": row}])[0].raw["owner_mailing"]
    assert om["absentee"] is False and om["out_of_state"] is False


def test_no_mailing_columns_means_no_owner_mailing_block():
    row = {**ROW_NEW, "CURR_ADDR1": "", "CURR_ADDR2": "", "CURR_CITY": "",
           "CURR_STATE": "", "CURR_ZIPCODE": ""}
    li = _run_fetch([{"attributes": row}])[0]
    assert "owner_mailing" not in li.raw
