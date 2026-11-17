"""Davidson County NC taxsearch.co.davidson.nc.us ViewTaxBill "Deferred Value" field ->
raw['rollback_exposure'].

The HTML fixture below is REAL, captured live 2026-11-17 from Davidson's own TaxBillSearch/
ViewTaxBill response (owner "HAMMER IDA S ESTATE", parcel "0100900000046", PIN
"6871-02-89-8474", 47.12-acre tract, tax year 2006-33433) -- not reconstructed by hand. That
real bill's own Deferred Value line reads 325,610 (a genuine present-use agricultural/forestry
deferral: Taxable Value 17,190 = Parcel Value Total 342,800 - Deferred Value 325,610, exact);
the zero variant below is that SAME real response with only the Deferred Value number changed,
the same technique test_harnett_rollback_exposure.py's own fixture already uses.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_davidson_rollback_exposure import (
    _addr_key, _eligible, build_block,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.verification.verifiers.tax_lien_itspublic import parse_view

#: Real ViewTaxBill response for taxYear=2006, billNumber=33433 (trimmed of the surrounding
#: page chrome this module doesn't read -- the fieldset markup itself is untouched).
VIEW_TAX_BILL_HAMMER = """
<br />
<hr class="result-divider" />
<h3>Tax Bill Information</h3>
<br />

    <div class="row">
            <div class="col-md-6">
                <fieldset>
                    <legend> Account Info</legend>
                    <ol>
                            <li>
 <div class="indiv info-row-label">Account Number :</div> <div class="indiv info-row-text" style='text-align: right'>3242600</div>                             </li>
                            <li>
HAMMER IDA S ESTATE                            </li>
                            <li>
1272 DAYTON AVE                            </li>
                            <li>
SAINT PAUL, MN 55104                            </li>
                        <li>
                        </li>
                    </ol>
                </fieldset>
            </div>
            <div class="col-md-6">
                <fieldset>
                    <legend> Bill Info</legend>
                    <ol>
                            <li>
 <div class="indiv info-row-label">Year-Bill Number :</div> <div class="indiv info-row-text" style='text-align: right'>2006-33433</div>                             </li>
                            <li>
 <div class="indiv info-row-label">Parcel Number :</div> <div class="indiv info-row-text" style='text-align: right'>0100900000046</div>                             </li>
                            <li>
 <div class="indiv info-row-label">PIN# :</div> <div class="indiv info-row-text" style='text-align: right'>6871-02-89-8474</div>                             </li>
                            <li>
 <div class="indiv info-row-label">Escrow :</div> <div class="indiv info-row-text" style='text-align: right'></div>                             </li>
                            <li>
 <div class="indiv info-row-label">Legal Description :</div> <div class="indiv info-row-text" style='text-align: right'>L46 BK490-486             WALLBURG HI P</div>                             </li>
                        <li>
                        </li>
                    </ol>
                </fieldset>
            </div>
            </div>
    <div class="row">
            <div class="col-md-6">
                <fieldset>
                    <legend> Taxable Values</legend>
                    <ol>
                            <li>
 <div class="indiv info-row-label">Building Value :</div> <div class="indiv info-row-text" style='text-align: right'>0</div>                             </li>
                            <li>
 <div class="indiv info-row-label">Outbuilding Value :</div> <div class="indiv info-row-text" style='text-align: right'>0</div>                             </li>
                            <li>
 <div class="indiv info-row-label">Land Value :</div> <div class="indiv info-row-text" style='text-align: right'>342,800</div>                             </li>
                            <li>
 <div class="indiv info-row-label">Parcel Value Total :</div> <div class="indiv info-row-text" style='text-align: right'>342,800</div>                             </li>
                            <li>
 <div class="indiv info-row-label">Deferred Value :</div> <div class="indiv info-row-text" style='text-align: right'>325,610</div>                             </li>
                            <li>
 <div class="indiv info-row-label">Taxable Value :</div> <div class="indiv info-row-text" style='text-align: right'>17,190</div>                             </li>
                        <li>
                        </li>
                    </ol>
                </fieldset>
            </div>
            <div class="col-md-6">
                <fieldset>
                    <legend> Balance Info</legend>
                    <ol>
                            <li>
 <div class="indiv info-row-label">Current Balance :</div> <div class="indiv info-row-text" style='text-align: right'>0.00</div>                             </li>
                            <li>
 <div class="indiv info-row-label">Original Levy :</div> <div class="indiv info-row-text" style='text-align: right'>110.02</div>                             </li>
                        <li>
                        </li>
                    </ol>
                </fieldset>
            </div>
            </div>
"""

#: The SAME real response, a non-present-use parcel: only the Deferred Value number is
#: changed to 0 (every other field, including Parcel/Taxable Value, stays as the real response
#: wrote it -- this module reads Deferred Value directly off its own labelled line, never
#: derives it from a Parcel-Taxable difference).
VIEW_TAX_BILL_ZERO_DEFERRED = VIEW_TAX_BILL_HAMMER.replace(
    "Deferred Value :</div> <div class=\"indiv info-row-text\" style='text-align: right'>325,610</div>",
    "Deferred Value :</div> <div class=\"indiv info-row-text\" style='text-align: right'>0</div>")


def _li(owner_name, street_address, county="Davidson", **kw) -> Listing:
    now = datetime.utcnow()
    return Listing(source="counties_nc.test", source_url="https://x/1",
                   listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                   county=county, state="NC", owner_name=owner_name,
                   street_address=street_address, first_seen=now, last_seen=now,
                   raw=kw.pop("raw", {}), **kw)


# ---------------------------------------------------------------------------
# parse_view (reused unmodified from the verifier) + build_block
# ---------------------------------------------------------------------------

def test_real_response_parses_deferred_value_and_parcel_value_total():
    view = parse_view(VIEW_TAX_BILL_HAMMER)
    assert view["Deferred Value"] == "325,610"
    assert view["Parcel Value Total"] == "342,800"
    assert view["Taxable Value"] == "17,190"
    assert view["Year-Bill Number"] == "2006-33433"


def test_zero_deferred_is_not_a_rollback_record():
    view = parse_view(VIEW_TAX_BILL_ZERO_DEFERRED)
    assert build_block(view) is None


def test_positive_deferred_gets_its_real_value_and_identity():
    view = parse_view(VIEW_TAX_BILL_HAMMER)
    rec = build_block(view)
    assert rec is not None
    assert rec["deferred_value"] == 325610.0
    assert rec["parcel_value_total"] == 342800.0
    assert rec["county"] == "Davidson" and rec["state"] == "NC"
    assert rec["basis"] == "present_use_deferral"
    assert rec["rollback_years"] == 4
    assert rec["tax_year"] == "2006"
    assert rec["match_method"] == "owner_name+street_address"
    # no rate source for this vendor (Davidson is not an nc_its_public_tax.py roll county):
    # never assumed, same discipline as every sibling rollback module.
    assert "estimated_rollback" not in rec
    assert "effective_tax_rate" not in rec


def test_a_missing_current_balance_marker_means_not_a_real_bill_page():
    """build_block() itself doesn't gate on this (the caller does, same as the verifier's own
    view()), but parse_view() must still return the label actually present so that guard works
    upstream."""
    view = parse_view(VIEW_TAX_BILL_HAMMER)
    assert "Current Balance" in view


# ---------------------------------------------------------------------------
# _eligible
# ---------------------------------------------------------------------------

def test_eligible_requires_davidson_an_owner_and_a_street_address():
    assert _eligible(_li("SMITH KEITH EDWARD", "916 Ferndale Dr"))
    assert not _eligible(_li("SMITH KEITH EDWARD", "916 Ferndale Dr", county="Harnett"))
    assert not _eligible(_li("SMITH KEITH EDWARD", None))
    assert not _eligible(_li(None, "916 Ferndale Dr"))


def test_a_company_owner_is_never_targeted():
    assert not _eligible(_li("00 F150 HOLDING TRUST", "1272 Dayton Ave"))


def test_an_existing_rollback_record_is_never_re_targeted():
    li = _li("HAMMER IDA S ESTATE", "1272 Dayton Ave",
            raw={"rollback_exposure": {"deferred_value": 325610.0}})
    assert not _eligible(li)


# ---------------------------------------------------------------------------
# _addr_key
# ---------------------------------------------------------------------------

def test_addr_key_matches_house_number_and_first_street_word_loosely():
    assert _addr_key("916 Ferndale Dr") == _addr_key("916 FERNDALE DRIVE")
    assert _addr_key("357 V V Willard Rd") != _addr_key("916 Ferndale Dr")
    assert _addr_key(None) == ""
