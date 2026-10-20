"""Hyde County NC lrcpwa.ncptscloud.com "Deferred" fields -> raw['rollback_exposure'].

The detail dicts below are REAL, captured live 2026-10-20 from lrcpwa.ncptscloud.com's own
getParcelDetails response (X-Tenant: Hyde) -- not reconstructed by hand. Parcel pk=3 (PIN
9500-18-5274, O'NEAL) is not under present use (useValueDeferred null); parcel pk=1600 (PIN
7683-12-4671, COMM/INDUSTRIAL) is, with totalDeferredValue 65,743 = totalLandValueAssessed
117,954 - landUseValue 52,211 exactly, the same market-minus-use identity Wake's and
Mecklenburg's own "Deferred" fields already verified for this project's rollback family --
trimmed here to the fields build_block()/rate_from_ptscloud_bill() actually read.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_hyde_rollback_exposure import (
    _digits, _eligible, build_block, rate_from_ptscloud_bill,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

#: Real getParcelDetails response, parcel pk=3 (not present-use).
DETAIL_ONEAL = {
    "formattedPin": "9500-18-5274", "pin": "9500185274", "taxYear": "2026",
    "landClass": "LOT VALUE", "zoning": "AGRICULTURAL DISTRICT",
    "totalLandValueAssessed": 192600, "totalBuildingValueAssessed": 155627,
    "landUseValue": 192600, "useValueDeferred": None, "historicValueDeferred": 0,
    "totalDeferredValue": 0, "totalPropertyValue": 348227,
}

#: Real getParcelDetails response, parcel pk=1600 (present-use, COMM/INDUSTRIAL).
DETAIL_PRESENT_USE = {
    "formattedPin": "7683-12-4671", "pin": "7683124671", "taxYear": "2026",
    "landClass": "COMM/INDUSTRIAL", "zoning": "NO ZONING",
    "totalLandValueAssessed": 117954, "totalBuildingValueAssessed": 0,
    "landUseValue": 52211, "useValueDeferred": 65743, "historicValueDeferred": 0,
    "totalDeferredValue": 65743, "totalPropertyValue": 52211,
}


def _li(parcel_id, county="Hyde", **kw) -> Listing:
    now = datetime.utcnow()
    return Listing(source="counties_nc.test", source_url="https://x/1",
                   listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                   county=county, state="NC", owner_name=kw.pop("owner_name", "SOMEONE"),
                   parcel_id=parcel_id, first_seen=now, last_seen=now,
                   raw=kw.pop("raw", {}), **kw)


# ---------------------------------------------------------------------------
# build_block: never invents a rollback record off a zero/blank deferred value
# ---------------------------------------------------------------------------

def test_a_non_present_use_parcel_is_not_a_rollback_record():
    assert build_block(DETAIL_ONEAL, {}) is None


def test_a_present_use_parcel_restates_the_real_deferred_value():
    rec = build_block(DETAIL_PRESENT_USE, {})
    assert rec is not None
    assert rec["deferred_value"] == 65743.0
    assert rec["county"] == "Hyde" and rec["state"] == "NC"
    assert rec["rollback_years"] == 4
    assert rec["match_method"] == "parcel"
    assert "estimated_rollback" not in rec       # no matching bill on the row: never assumed


def test_useValueDeferred_is_the_fallback_when_totalDeferredValue_is_absent():
    detail = {k: v for k, v in DETAIL_PRESENT_USE.items() if k != "totalDeferredValue"}
    rec = build_block(detail, {})
    assert rec["deferred_value"] == 65743.0


def test_a_matching_bill_year_derives_a_real_rate():
    raw = {"nc_ptscloud_delinquent_tax": {
        "by_year": [{"tax_year": "2026", "bill_amount": 391.58}]}}
    rec = build_block(DETAIL_PRESENT_USE, raw)
    rate = 391.58 / 52211.0
    assert rec["effective_tax_rate"] == round(rate, 6)
    assert rec["annual_deferred_tax"] == round(65743.0 * rate, 2)
    assert rec["estimated_rollback"] == round(rec["annual_deferred_tax"] * 4, 2)
    assert rec["tax_rate_source"] == "nc_ptscloud_delinquent_tax_bill"


def test_a_bill_for_a_different_year_is_never_used():
    raw = {"nc_ptscloud_delinquent_tax": {
        "by_year": [{"tax_year": "2024", "bill_amount": 391.58}]}}
    rec = build_block(DETAIL_PRESENT_USE, raw)
    assert "estimated_rollback" not in rec


def test_an_implausible_rate_is_never_used():
    raw = {"nc_ptscloud_delinquent_tax": {
        "by_year": [{"tax_year": "2026", "bill_amount": 52211.0 * 0.5}]}}
    rec = build_block(DETAIL_PRESENT_USE, raw)
    assert "estimated_rollback" not in rec


# ---------------------------------------------------------------------------
# rate_from_ptscloud_bill
# ---------------------------------------------------------------------------

def test_rate_helper_needs_a_dict_source_and_a_positive_assessed_value():
    assert rate_from_ptscloud_bill({}, 52211.0, "2026") is None
    assert rate_from_ptscloud_bill({"nc_ptscloud_delinquent_tax": {"by_year": []}}, None, "2026") is None
    assert rate_from_ptscloud_bill({"nc_ptscloud_delinquent_tax": "not a dict"}, 52211.0, "2026") is None


# ---------------------------------------------------------------------------
# _eligible / _digits
# ---------------------------------------------------------------------------

def test_digits_strips_dashes_and_the_formatted_pin_matches():
    assert _digits("9500-18-5274") == "9500185274"
    assert _digits(None) == ""


def test_eligible_requires_hyde_nc_and_a_bare_pin_shaped_parcel_id():
    assert _eligible(_li("9500185274"))
    assert not _eligible(_li("9500185274", county="Beaufort"))
    assert not _eligible(_li("02559-J10-15"))     # Hyde's legacy tax-map notation, not a PIN
    assert not _eligible(_li(None))


def test_an_existing_rollback_record_is_never_re_targeted():
    li = _li("9500185274", raw={"rollback_exposure": {"deferred_value": 65743.0}})
    assert not _eligible(li)
