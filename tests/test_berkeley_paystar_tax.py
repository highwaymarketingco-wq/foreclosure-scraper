"""Tests for Berkeley County SC paystar.io delinquent-tax parser."""
import json

from foreclosure_scraper.scrapers.counties_sc.berkeley_paystar_tax import (
    _detail_to_listing,
    _full_addr,
    _meta,
)

_REAL_DETAIL = {
    "invoiceNumber": "2025-0059823",
    "invoiceNumberHash": "MjAyNS0wMDU5ODIz",
    "taxYear": 2025,
    "invoiceAmountMinor": 28943,
    "payable": True,
    "delinquent": True,
    "invoiceeName": "HOWELL GAIL SMITH",
    "invoiceStreetAddress1": "2343HIGHWAY 311",
    "invoiceStreetAddress2": "",
    "invoiceCity": "CROSS",
    "invoiceState": "SC",
    "invoicePostalCode": "29436",
    "status": "Unpaid",
    "assetType": "Real Property",
    "assetIdentifierDisplay": "078-00-00-085",
    "assetOwner": "HOWELL GAIL SMITH",
    "assetMetaJson": json.dumps({
        "Identifier": "078-00-00-085",
        "SiteAddress": "329 OLD COMMUNITY RD",
        "SiteCity": "CROSS",
        "SiteState": "SC",
        "SiteZip": "29436",
        "BillName": "HOWELL GAIL SMITH",
        "BillAddress1": "2343HIGHWAY 311",
        "AcresCount": "1.00",
        "TotalAssessment": "1100",
        "QRLandValue": "14000",
        "QRBuildingValue": "13500",
        "DeedBook": "0949",
        "DeedPage": "0247",
        "ParentTMS": "0780000050",
        "Millage": ".24650",
        "TaxesDue": "289.43",
        "ResidentialAssessmentExemption": "1100",
    }),
}


def test_real_sample_produces_a_correct_listing():
    li = _detail_to_listing(_REAL_DETAIL, "MjAyNS0wMDU5ODIz")
    assert li is not None
    assert li.parcel_id == "078-00-00-085"
    assert li.owner_name == "HOWELL GAIL SMITH"
    assert li.street_address == "329 OLD COMMUNITY RD"          # SITUS, not mailing
    assert li.city == "CROSS"
    assert li.zip_code == "29436"
    assert li.case_number == "2025-0059823"
    assert li.county == "Berkeley"
    assert li.state == "SC"


def test_situs_and_mailing_are_kept_distinct_and_absentee_is_flagged_on_a_street_mismatch():
    li = _detail_to_listing(_REAL_DETAIL, "MjAyNS0wMDU5ODIz")
    om = li.raw["owner_mailing"]
    assert om["situs"] == "329 OLD COMMUNITY RD CROSS, SC 29436"
    assert om["mailing"] == "2343HIGHWAY 311 CROSS, SC 29436"
    # Same city/state, but the STREET differs (rural highway mailing address
    # vs. the parcel's own road) -- _is_absentee's substring/token-subset
    # test correctly does not match these, so this real sample IS flagged
    # absentee even though it never left South Carolina. Pinned to the
    # actual value (verified live 2026-09-15), not just isinstance(bool),
    # so a change to _is_absentee's tolerance shows up here.
    assert om["absentee"] is True
    assert om["out_of_state"] is False   # mail_state SC == property state SC


def test_out_of_state_mailing_is_flagged():
    detail = dict(_REAL_DETAIL)
    detail["invoiceState"] = "GA"
    detail["invoicePostalCode"] = "30301"
    li = _detail_to_listing(detail, "MjAyNS0wMDU5ODIz")
    om = li.raw["owner_mailing"]
    assert om["mail_state"] == "GA"
    assert om["out_of_state"] is True
    assert om["absentee"] is True   # different city entirely can't be a substring/subset match


def test_amount_is_converted_from_minor_units():
    li = _detail_to_listing(_REAL_DETAIL, "MjAyNS0wMDU5ODIz")
    assert li.raw["berkeley_paystar_tax"]["total_due"] == 289.43


def test_zero_or_missing_amount_is_dropped():
    detail = dict(_REAL_DETAIL)
    detail["invoiceAmountMinor"] = 0
    detail["assetMetaJson"] = json.dumps({})   # no TaxesDue fallback either
    assert _detail_to_listing(detail, "x") is None


def test_no_parcel_and_no_owner_is_dropped():
    detail = dict(_REAL_DETAIL)
    detail["assetIdentifierDisplay"] = None
    detail["assetOwner"] = None
    detail["invoiceeName"] = None
    detail["assetMetaJson"] = json.dumps({})
    assert _detail_to_listing(detail, "x") is None


def test_missing_asset_meta_json_still_yields_a_bare_listing():
    detail = dict(_REAL_DETAIL)
    detail["assetMetaJson"] = None
    li = _detail_to_listing(detail, "MjAyNS0wMDU5ODIz")
    assert li is not None
    assert li.parcel_id == "078-00-00-085"
    assert li.street_address is None    # no SITUS available without assetMetaJson
    # Mailing is still on the top-level invoice fields, independent of assetMetaJson.
    assert li.raw["owner_mailing"]["mailing"] == "2343HIGHWAY 311 CROSS, SC 29436"


def test_malformed_asset_meta_json_does_not_raise():
    detail = dict(_REAL_DETAIL)
    detail["assetMetaJson"] = "{not valid json"
    assert _meta(detail) == {}
    li = _detail_to_listing(detail, "x")
    assert li is not None   # still resolves from top-level fields


def test_full_addr_omits_missing_pieces():
    assert _full_addr("123 Main St", "Anytown", "SC", "29401") == "123 Main St Anytown, SC 29401"
    assert _full_addr(None, None, None, None) is None
    assert _full_addr("123 Main St", None, None, None) == "123 Main St"


def test_deed_and_valuation_fields_reach_the_raw_block():
    li = _detail_to_listing(_REAL_DETAIL, "MjAyNS0wMDU5ODIz")
    blk = li.raw["berkeley_paystar_tax"]
    assert blk["deed_book"] == "0949"
    assert blk["deed_page"] == "0247"
    assert blk["parent_tms"] == "0780000050"
    assert blk["appraised_value"] == 27500.0
    assert blk["assessed_value"] == 1100.0
    assert blk["acres"] == 1.0
    assert blk["tax_year"] == 2025
    assert blk["delinquent"] is True
