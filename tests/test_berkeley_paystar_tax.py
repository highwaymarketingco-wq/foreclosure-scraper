"""Tests for Berkeley County SC paystar.io delinquent-tax parser."""
import json
from datetime import datetime

from foreclosure_scraper.scrapers.counties_sc.berkeley_paystar_tax import (
    _detail_to_listing,
    _full_addr,
    _meta,
    _not_yet_due_rows,
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


# ---------------------------------------------------------------------------
# 2026-10-03 fix: the current (not-yet-due) tax year must never be published as
# a delinquent lead, even though the portal's own "Unpaid" status covers it too.
# See _not_yet_due_rows' docstring in the source module for the live numbers
# (an unfiltered search balloons from ~3,426 real rows to 123,450 the week the
# new annual roll loads).
# ---------------------------------------------------------------------------

def test_explicit_delinquent_false_is_dropped_even_with_a_real_balance():
    """A real live sample from the week the 2026 roll loaded: a nonzero TaxesDue
    ($1,813.29) but delinquent=false and no issue/due date yet -- a freshly-issued
    bill, not a lead."""
    detail = dict(_REAL_DETAIL)
    detail["delinquent"] = False
    detail["taxYear"] = 2026
    detail["invoiceAmountMinor"] = 181329
    assert _detail_to_listing(detail, "x") is None


def test_delinquent_true_or_missing_still_passes():
    # delinquent=True (the real fixture) already covered by other tests above;
    # confirm a MISSING delinquent key (older/partial payloads) is not treated
    # the same as an explicit False -- "uncertain" must not silently drop a row.
    detail = dict(_REAL_DETAIL)
    del detail["delinquent"]
    assert _detail_to_listing(detail, "MjAyNS0wMDU5ODIz") is not None


def test_not_yet_due_rows_drops_only_the_current_tax_year():
    current_year = datetime.utcnow().year
    rows = [
        {"invoiceNumberHash": "a", "taxYear": current_year},       # fresh bill, drop
        {"invoiceNumberHash": "b", "taxYear": current_year - 1},   # real prior-year, keep
        {"invoiceNumberHash": "c", "taxYear": current_year - 5},   # real prior-year, keep
        {"invoiceNumberHash": "d"},                                 # missing taxYear, keep (conservative)
    ]
    kept = {r["invoiceNumberHash"] for r in _not_yet_due_rows(rows)}
    assert kept == {"b", "c", "d"}


def test_not_yet_due_rows_handles_empty_and_all_current_year():
    assert _not_yet_due_rows([]) == []
    current_year = datetime.utcnow().year
    rows = [{"invoiceNumberHash": "x", "taxYear": current_year}]
    assert _not_yet_due_rows(rows) == []


# ---------------------------------------------------------------------------
# _prior_tax_years: the server-side scoping that avoids the page-ordering trap
# (see _list_all's docstring -- paging an unfiltered search put all 120k+
# current-year rows before any real prior-year one, so the old client-side-only
# filter shipped 0 once the new roll loaded).
# ---------------------------------------------------------------------------

import asyncio

from foreclosure_scraper.scrapers.counties_sc.berkeley_paystar_tax import _prior_tax_years


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    """Stands in for httpx.AsyncClient for _prior_tax_years -- just needs .post()."""

    def __init__(self, payload):
        self._payload = payload
        self.last_json = None

    async def post(self, url, json):
        self.last_json = json
        return _FakeResp(self._payload)


def _facets_payload(year_counts: dict[int, int]) -> dict:
    return {"data": {"facets": [
        {"facetName": "TaxYear", "facetValues": [
            {"propertyValue": str(y), "count": c} for y, c in year_counts.items()
        ]},
    ]}}


def test_prior_tax_years_excludes_only_the_max_year():
    payload = _facets_payload({2026: 120359, 2025: 2085, 2024: 363, 2016: 31})
    client = _FakeClient(payload)
    years = asyncio.run(_prior_tax_years(client))
    assert years is not None
    assert set(years) == {"2025", "2024", "2016"}
    assert "2026" not in years


def test_prior_tax_years_returns_none_on_missing_facets():
    client = _FakeClient({"data": {"facets": []}})
    assert asyncio.run(_prior_tax_years(client)) is None


def test_prior_tax_years_returns_none_on_request_failure():
    class _RaisingClient:
        async def post(self, url, json):
            raise RuntimeError("boom")

    assert asyncio.run(_prior_tax_years(_RaisingClient())) is None


# --- 2026-10-07 extraction audit: assetMetaJson keys the detail call already returns.
# Names and values below are made up. ---

def _detail_with(meta_extra: dict) -> dict:
    d = dict(_REAL_DETAIL)
    d["invoiceeName"] = d["assetOwner"] = "SAMPLE PAT"
    base = json.loads(_REAL_DETAIL["assetMetaJson"])
    base.update({"BillName": "SAMPLE PAT", **meta_extra})
    d["assetMetaJson"] = json.dumps(base)
    return d


def test_bill_breakdown_homestead_and_districts_are_captured():
    li = _detail_to_listing(_detail_with({
        "TaxesDue": "300.00", "TaxPenalties": "45.00", "DLQPenalties": "30.00",
        "TaxTotal": "375.00", "BillTotal": "390.00", "TaxesDuePenalty1": "309.00",
        "Penalty1Date": "2026-01-15", "HomesteadExemption": "50000",
        "HomesteadPercentage": "100", "HomesteadApplicationYear": "2019",
        "DelinquentCode": "D", "TaxDistrict": "01", "FireDistrict": "F2",
        "AccountNum": "A-1", "ReceiptNumber": "R-1", "TotalBuildingCount": "1",
        "OTBuildingValue": "", "AgLandValue": "0"}), "h")
    b = li.raw["berkeley_paystar_tax"]
    assert b["taxes_due"] == 300.0 and b["tax_penalties"] == 45.0 and b["dlq_penalties"] == 30.0
    assert b["tax_total"] == 375.0 and b["bill_total"] == 390.0
    assert b["taxes_due_penalty1"] == 309.0 and b["penalty1_date"] == "2026-01-15"
    assert b["homestead_exemption"] == 50000.0 and b["homestead_application_year"] == "2019"
    assert b["delinquent_code"] == "D" and b["tax_district"] == "01"
    assert b["account_number"] == "A-1" and b["receipt_number"] == "R-1"
    assert b["building_count"] == 1.0
    assert "ot_building_value" not in b and "ag_land_value" not in b   # blank / 0 -> absent


def test_appraised_value_sums_every_assessment_class():
    """QR alone left a non-owner-occupied (OT) parcel with no appraised value."""
    ot = _detail_with({"QRLandValue": "", "QRBuildingValue": "",
                       "OTLandValue": "20000", "OTBuildingValue": "60000"})
    b = _detail_to_listing(ot, "h").raw["berkeley_paystar_tax"]
    assert b["appraised_value"] == 80000.0
    assert b["ot_land_value"] == 20000.0 and b["ot_building_value"] == 60000.0
    qr = _detail_to_listing(_REAL_DETAIL, "h").raw["berkeley_paystar_tax"]
    assert qr["appraised_value"] == 27500.0                 # QR-only: unchanged


def test_all_zero_text_codes_are_blank_not_values():
    b = _detail_to_listing(_detail_with({"Sub": "000", "Block": "0", "Lot": "12"}), "h"
                           ).raw["berkeley_paystar_tax"]
    assert "subdivision" not in b and "block" not in b and b["lot"] == "12"
