"""Harnett County NC cama.harnett.org/ITSPublicHT "Deferred" field -> raw['rollback_exposure'].

The HTML fixture below is REAL, captured live 2026-10-20 from Harnett's own BasicSearch
ViewParcel response (owner "PENNY ROAD DEVELOPERS LLC", parcel "110662    0022 37", tax year
2027) -- not reconstructed by hand. That real parcel's own Deferred line reads 0 (not under
present use); the nonzero variant used below is that SAME real response with only the Deferred
number changed, the same technique test_bt_parcel_info.py's own
test_a_blank_deed_book_page_is_never_invented() already uses for its edge case.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_bt_parcel_info import parse_view_parcel
from foreclosure_scraper.enrichment_harnett_rollback_exposure import (
    build_block, _eligible, rate_from_its_public_tax,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

#: Real ViewParcel response for parcelNumber="110662    0022 37", taxYear=2027 (trimmed of the
#: Parcel Number / Property Information / Township / Local Zoning / Sales-Information tab
#: fieldsets, which this module doesn't read -- the markup shape of every fieldset is identical,
#: so the trim doesn't change what's being tested).
VIEW_PARCEL_PENNY_ROAD = """
<div class="row">
        <div class="col-md-6">
            <fieldset>
                <legend> Account Number</legend>
                <ol>
                        <li>
1500028131                            </li>
                    <li>
                    </li>
                </ol>
            </fieldset>
        </div>
        </div>
<div class="row">
        <div class="col-md-6">
            <fieldset>
                <legend> Owner Information</legend>
                <ol>
                        <li>
PENNY ROAD DEVELOPERS LLC                            </li>
                        <li>
                        </li>
                        <li>
1611 JONES FRANKLIN RD                            </li>
                        <li>
RALEIGH, NC 27606                            </li>
                    <li>
                    </li>
                </ol>
            </fieldset>
        </div>
        </div>
<div class="row">
        <div class="col-md-6">
            <fieldset>
                <legend> Deed Information</legend>
                <ol>
                        <li>
 <div class="indiv info-row-label">Deed Date :</div> <div class="indiv info-row-text" style='text-align: right'>8/30/2018</div>                             </li>
                        <li>
 <div class="indiv info-row-label">Deed Book/Page :</div> <div class="indiv info-row-text" style='text-align: right'>03635 / 0819</div>                             </li>
                        <li>
 <div class="indiv info-row-label">Plat Book/Page :</div> <div class="indiv info-row-text" style='text-align: right'>2019 / 338</div>                             </li>
                    <li>
                    </li>
                </ol>
            </fieldset>
        </div>
        </div>
<div class="row">
        <div class="col-md-6">
            <fieldset>
                <legend> Property Values</legend>
                <ol>
                        <li>
 <div class="indiv info-row-label">Building :</div> <div class="indiv info-row-text" style='text-align: right'>0</div>                             </li>
                        <li>
 <div class="indiv info-row-label">Obxf :</div> <div class="indiv info-row-text" style='text-align: right'>0</div>                             </li>
                        <li>
 <div class="indiv info-row-label">Land :</div> <div class="indiv info-row-text" style='text-align: right'>67,320</div>                             </li>
                        <li>
 <div class="indiv info-row-label">Market :</div> <div class="indiv info-row-text" style='text-align: right'>67,320</div>                             </li>
                        <li>
 <div class="indiv info-row-label">Assessed :</div> <div class="indiv info-row-text" style='text-align: right'>67,320</div>                             </li>
                        <li>
 <div class="indiv info-row-label">Deferred :</div> <div class="indiv info-row-text" style='text-align: right'>0</div>                             </li>
                        <li>
 <div class="indiv info-row-label">Exemption(s) :</div> <div class="indiv info-row-text" style='text-align: right'></div>                             </li>
                    <li>
                    </li>
                </ol>
            </fieldset>
        </div>
        </div>
<div class="row">
        <div class="col-md-6">
            <fieldset>
                <legend> Legal Description</legend>
                <ol>
                        <li>
TR#2 PENNY ROAD DEVELOPMENT MAP#2019-338                            </li>
                    <li>
                    </li>
                </ol>
            </fieldset>
        </div>
        </div>
"""

#: The SAME real response, present-use case: only the Deferred number is changed (67,320 land
#: value with a 14,200 deferred present-use gap -- Assessed stays as the real response wrote it;
#: this module reads Deferred directly off its own labelled line, never derives it from a
#: Market-Assessed difference).
VIEW_PARCEL_PRESENT_USE = VIEW_PARCEL_PENNY_ROAD.replace(
    "Deferred :</div> <div class=\"indiv info-row-text\" style='text-align: right'>0</div>",
    "Deferred :</div> <div class=\"indiv info-row-text\" style='text-align: right'>14,200</div>")


def _li(owner_name, street_address, county="Harnett", **kw) -> Listing:
    now = datetime.utcnow()
    return Listing(source="counties_nc.test", source_url="https://x/1",
                   listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                   county=county, state="NC", owner_name=owner_name,
                   street_address=street_address, first_seen=now, last_seen=now,
                   raw=kw.pop("raw", {}), **kw)


# ---------------------------------------------------------------------------
# parse_view_parcel: the shared parser's new Deferred extraction
# ---------------------------------------------------------------------------

def test_real_response_reads_deferred_even_when_zero():
    """A real parcel not under present use: Deferred parses as 0.0, same as Market/Assessed --
    parse_view_parcel() never special-cases zero (the "never invented" guard lives in
    build_block(), not here)."""
    got = parse_view_parcel(VIEW_PARCEL_PENNY_ROAD)
    assert got["deferred_value"] == 0.0
    assert got["market_value"] == got["assessed_value"] == 67320.0


def test_present_use_variant_reads_the_nonzero_deferred_value():
    got = parse_view_parcel(VIEW_PARCEL_PRESENT_USE)
    assert got["deferred_value"] == 14200.0


# ---------------------------------------------------------------------------
# build_block: never invents a rollback record off a zero/blank Deferred
# ---------------------------------------------------------------------------

def test_zero_deferred_is_not_a_rollback_record():
    detail = parse_view_parcel(VIEW_PARCEL_PENNY_ROAD)
    assert build_block(detail, {}) is None


def test_positive_deferred_without_a_matching_tax_bill_still_gets_its_real_value():
    detail = parse_view_parcel(VIEW_PARCEL_PRESENT_USE)
    detail["tax_year"] = "2027"
    rec = build_block(detail, {})
    assert rec is not None
    assert rec["deferred_value"] == 14200.0
    assert rec["county"] == "Harnett" and rec["state"] == "NC"
    assert rec["rollback_years"] == 4
    assert "estimated_rollback" not in rec       # no rate derivable: never assumed


def test_positive_deferred_with_a_matching_bill_derives_a_real_rate():
    detail = parse_view_parcel(VIEW_PARCEL_PRESENT_USE)
    detail["tax_year"] = "2027"
    raw = {"nc_its_public_tax": {"bills": [{"year": 2027, "original_levy": 672.0, "balance": 672.0}]}}
    rec = build_block(detail, raw)
    assert rec["effective_tax_rate"] == round(672.0 / 67320.0, 6)
    assert rec["annual_deferred_tax"] == round(14200.0 * (672.0 / 67320.0), 2)
    assert rec["estimated_rollback"] == round(rec["annual_deferred_tax"] * 4, 2)
    assert rec["tax_rate_source"] == "nc_its_public_tax_bill"


def test_a_bill_for_a_different_year_is_never_used():
    detail = parse_view_parcel(VIEW_PARCEL_PRESENT_USE)
    detail["tax_year"] = "2027"
    raw = {"nc_its_public_tax": {"bills": [{"year": 2024, "original_levy": 672.0, "balance": 672.0}]}}
    rec = build_block(detail, raw)
    assert "estimated_rollback" not in rec


def test_an_implausible_rate_is_never_used():
    """A levy/assessed ratio outside the sane band (_RATE_MIN/_RATE_MAX) is not a real combined
    tax rate -- same guard every sibling rollback section applies."""
    detail = parse_view_parcel(VIEW_PARCEL_PRESENT_USE)
    detail["tax_year"] = "2027"
    raw = {"nc_its_public_tax": {"bills": [{"year": 2027, "original_levy": 67320.0 * 0.5,
                                            "balance": 1.0}]}}
    rec = build_block(detail, raw)
    assert "estimated_rollback" not in rec


# ---------------------------------------------------------------------------
# rate_from_its_public_tax
# ---------------------------------------------------------------------------

def test_rate_helper_needs_a_dict_source_and_a_positive_assessed_value():
    assert rate_from_its_public_tax({}, 67320.0, "2027") is None
    assert rate_from_its_public_tax({"nc_its_public_tax": {"bills": []}}, None, "2027") is None
    assert rate_from_its_public_tax({"nc_its_public_tax": "not a dict"}, 67320.0, "2027") is None


# ---------------------------------------------------------------------------
# _eligible
# ---------------------------------------------------------------------------

def test_eligible_requires_harnett_an_owner_and_a_street_address():
    assert _eligible(_li("RUBIO ASHLEY", "641 White Birch Lane"))
    assert not _eligible(_li("RUBIO ASHLEY", "641 White Birch Lane", county="Warren"))
    assert not _eligible(_li("RUBIO ASHLEY", None))
    assert not _eligible(_li(None, "641 White Birch Lane"))


def test_a_company_owner_is_never_targeted():
    assert not _eligible(_li("PENNY ROAD DEVELOPERS LLC", "HARNETT CENTRAL RD"))


def test_an_existing_rollback_record_is_never_re_targeted():
    li = _li("RUBIO ASHLEY", "641 White Birch Lane",
            raw={"rollback_exposure": {"deferred_value": 14200.0}})
    assert not _eligible(li)
