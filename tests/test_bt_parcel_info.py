"""BT TaxPayer Portal "Parcel Information" panel: legal description + deed ref, 14 NC counties.

The JSON/HTML fixtures below are REAL, captured live 2026-10-16 from Warren County
(ITSPublicWN) searching the real board owner "GIBSON WALTER CLIFTON III" at
437 Quail Ridge Road -- not reconstructed by hand. The 10-row GIBSON search result and the
ViewParcel response for the matching row (parcel L2D74, tax year 2027) are both real.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_bt_parcel_info import (
    _best_match, _eligible, _search_query, parse_search_rows, parse_view_parcel,
)

#: Real GetSearchTableData response for OwnerName="GIBSON" on Warren County (10 rows; trimmed
#: to the 3 that matter for the tests below -- a no-address row, a decoy at a different house
#: number on a DIFFERENT street, and the real target).
SEARCH_RESPONSE_GIBSON = {
    "total": 1,
    "numRecords": 10,
    "rows": [
        {"id": "K640/2027",
         "cell": ["GIBSON EULA R HEIRS", None, None, "1 AC", "K640", "", "2027",
                  "<a href='https://www.bttaxpayerportal.com/ITSPublicWN/AppraisalCard.aspx?"
                  "id=K640/2027' target='_blank'>PRC</a>"]},
        {"id": "K639C/2027",
         "cell": ["GIBSON JOHN W & CONNIE P", None, "3640 US HIGHWAY 158 E", "5.54 AC", "K639C",
                  "", "2027", "<a href='...'>PRC</a>"]},
        {"id": "L2D74/2027",
         "cell": ["GIBSON WALTER CLIFTON III TRUSTEE OF THE WALTER C",
                  "GIBSON FAMILY REVOCABLE TRUST", "437 QUAIL RIDGE RD", "0 AC", "L2D74", "",
                  "2027", "<a href='...'>PRC</a>"]},
    ],
}

#: Real ViewParcel response for parcelNumber=L2D74, taxYear=2027 (trimmed of the Tax Codes /
#: Property Information / Township / Local Zoning / AlternateParcelBasicSearchText fieldsets,
#: which this module doesn't read -- the markup shape of every fieldset is identical, so the
#: trim doesn't change what's being tested).
VIEW_PARCEL_GIBSON = """
<br />
<hr class="result-divider" />
<h3>Parcel Information</h3>
<br />
    <div class="row">
            <div class="col-md-6">
                <fieldset>
                    <legend> Parcel Number</legend>
                    <ol>
                            <li>
L2D74                            </li>
                        <li>
                        </li>
                    </ol>
                </fieldset>
            </div>
            <div class="col-md-6">
                <fieldset>
                    <legend> Account Number</legend>
                    <ol>
                            <li>
55045                            </li>
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
GIBSON WALTER CLIFTON III TRUSTEE OF THE WALTER C                            </li>
                            <li>
GIBSON FAMILY REVOCABLE TRUST                            </li>
                            <li>
PO BOX 214                            </li>
                            <li>
ROLESVILLE, NC 27571                            </li>
                        <li>
                        </li>
                    </ol>
                </fieldset>
            </div>
            <div class="col-md-6">
                <fieldset>
                    <legend> Tax Codes</legend>
                    <ol>
                            <li>
C   ADVLTAX - Warren County                            </li>
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
 <div class="indiv info-row-label">Deed Date :</div> <div class="indiv info-row-text" style='text-align: right'>7/6/2026</div>                             </li>
                            <li>
 <div class="indiv info-row-label">Deed Book/Page :</div> <div class="indiv info-row-text" style='text-align: right'>1173 / 0656</div>                             </li>
                            <li>
 <div class="indiv info-row-label">Plat Book/Page :</div> <div class="indiv info-row-text" style='text-align: right'>0000 / 0000</div>                             </li>
                        <li>
                        </li>
                    </ol>
                </fieldset>
            </div>
            <div class="col-md-6">
                <fieldset>
                    <legend> Local Zoning</legend>
                    <ol>
                            <li>
                            </li>
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
 <div class="indiv info-row-label">Building :</div> <div class="indiv info-row-text" style='text-align: right'>121,081</div>                             </li>
                            <li>
 <div class="indiv info-row-label">Market :</div> <div class="indiv info-row-text" style='text-align: right'>972,414</div>                             </li>
                            <li>
 <div class="indiv info-row-label">Assessed :</div> <div class="indiv info-row-text" style='text-align: right'>972,414</div>                             </li>
                        <li>
                        </li>
                    </ol>
                </fieldset>
            </div>
            <div class="col-md-6">
                <fieldset>
                    <legend> AlternateParcelBasicSearchText</legend>
                    <ol>
                            <li>
                            </li>
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
LT A9 &amp; HSE QUAIL RIDGE                            </li>
                        <li>
                        </li>
                    </ol>
                </fieldset>
            </div>
         <div class="col-md-6"></div>     </div>
"""


def _li(owner_name, street_address, county="Warren", **kw) -> Listing:
    now = datetime.utcnow()
    return Listing(source="counties_nc.test", source_url="https://x/1",
                   listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                   county=county, state="NC", owner_name=owner_name,
                   street_address=street_address, first_seen=now, last_seen=now,
                   raw=kw.pop("raw", {}), **kw)


# ---------------------------------------------------------------------------
# parse_search_rows: real captured JSON
# ---------------------------------------------------------------------------

def test_real_search_rows_parse_every_field():
    rows = parse_search_rows(SEARCH_RESPONSE_GIBSON)
    assert len(rows) == 3
    target = rows[2]
    assert target["parcel_number"] == "L2D74"
    assert target["tax_year"] == "2027"
    assert target["owner_name"] == "GIBSON WALTER CLIFTON III TRUSTEE OF THE WALTER C"
    assert target["co_owner"] == "GIBSON FAMILY REVOCABLE TRUST"
    assert target["property_address"] == "437 QUAIL RIDGE RD"


def test_a_row_with_no_address_still_parses_as_an_empty_string_not_a_crash():
    rows = parse_search_rows(SEARCH_RESPONSE_GIBSON)
    assert rows[0]["property_address"] == ""   # GIBSON EULA R HEIRS: cell[2] is None


def test_an_empty_or_malformed_response_yields_no_rows():
    assert parse_search_rows({}) == []
    assert parse_search_rows({"rows": []}) == []
    assert parse_search_rows({"rows": [{"id": "", "cell": []}]}) == []


# ---------------------------------------------------------------------------
# _best_match: the whole safety mechanism -- address AND owner, never one alone
# ---------------------------------------------------------------------------

def test_matching_address_and_owner_wins():
    li = _li("GIBSON WALTER CLIFTON III", "437 Quail Ridge Road")
    rows = parse_search_rows(SEARCH_RESPONSE_GIBSON)
    match = _best_match(li, rows)
    assert match is not None and match["parcel_number"] == "L2D74"


def test_right_owner_wrong_address_is_not_a_match():
    """The decoy row (GIBSON JOHN W, a different Gibson) must never win just because the
    surname matches -- confirms the address gate, not just the owner gate, is load-bearing."""
    li = _li("GIBSON WALTER CLIFTON III", "999 Nowhere Lane")
    rows = parse_search_rows(SEARCH_RESPONSE_GIBSON)
    assert _best_match(li, rows) is None


def test_right_address_wrong_owner_is_not_a_match():
    """A different person's name at a coincidentally similar address must not match either --
    the owner check is not redundant with the address check."""
    li = _li("SMITH JOHN", "437 Quail Ridge Road")
    rows = parse_search_rows(SEARCH_RESPONSE_GIBSON)
    assert _best_match(li, rows) is None


def test_no_candidates_is_not_a_match():
    li = _li("GIBSON WALTER CLIFTON III", "437 Quail Ridge Road")
    assert _best_match(li, []) is None


# ---------------------------------------------------------------------------
# parse_view_parcel: real captured HTML
# ---------------------------------------------------------------------------

def test_real_view_parcel_response_parses_every_field():
    got = parse_view_parcel(VIEW_PARCEL_GIBSON)
    assert got["account_number"] == "55045"
    assert got["legal_description"] == "LT A9 & HSE QUAIL RIDGE"      # &amp; decoded
    assert got["mailing_address"] == "GIBSON FAMILY REVOCABLE TRUST, PO BOX 214, ROLESVILLE, NC 27571"
    assert got["deed_date"] == "7/6/2026"
    assert got["deed_book"] == "1173"
    assert got["deed_page"] == "0656"
    assert got["market_value"] == 972414.0
    assert got["assessed_value"] == 972414.0


def test_a_blank_deed_book_page_is_never_invented():
    """Plat Book/Page reads '0000 / 0000' on a parcel with no plat -- the SAME placeholder
    shape a real deed book/page could in principle have, so the parser must not emit a
    deed_book/deed_page pair that is just that sentinel."""
    html = VIEW_PARCEL_GIBSON.replace(
        "Deed Book/Page :</div> <div class=\"indiv info-row-text\" style='text-align: right'>1173 / 0656</div>",
        "Deed Book/Page :</div> <div class=\"indiv info-row-text\" style='text-align: right'>0000 / 0000</div>")
    got = parse_view_parcel(html)
    assert "deed_book" not in got and "deed_page" not in got


def test_junk_input_yields_nothing():
    assert parse_view_parcel("") == {}
    assert parse_view_parcel("<html>server error</html>") == {}


# ---------------------------------------------------------------------------
# _search_query / _eligible
# ---------------------------------------------------------------------------

def test_search_query_is_surname_then_first_name():
    assert _search_query(_li("GIBSON WALTER CLIFTON III", "437 Quail Ridge Road")) == "GIBSON WALTER"


def test_search_query_is_none_for_an_unparseable_name():
    assert _search_query(_li("", "437 Quail Ridge Road")) is None


def test_eligible_requires_a_wired_county_an_owner_and_a_street_address():
    assert _eligible(_li("GIBSON WALTER CLIFTON III", "437 Quail Ridge Road", county="Warren"))
    assert not _eligible(_li("GIBSON WALTER CLIFTON III", "437 Quail Ridge Road", county="Mecklenburg"))
    assert not _eligible(_li("GIBSON WALTER CLIFTON III", None, county="Warren"))
    assert not _eligible(_li(None, "437 Quail Ridge Road", county="Warren"))


def test_a_company_owner_is_never_targeted():
    """is_entity() skip: this module's name_normalize.match_owner path is built for person
    names, and a loose company-name search would be a false-positive factory."""
    assert not _eligible(_li("Glen Raven Inc.", "268 US Hwy", county="Warren"))


def test_a_confirmed_match_is_never_re_targeted():
    """A real result never goes stale (a recorded deed doesn't change) -- unlike a negative
    "status" marker, which stays eligible here so the tail's own age-based _due() check (not
    this function) decides whether it's due for a retry."""
    li = _li("GIBSON WALTER CLIFTON III", "437 Quail Ridge Road", county="Warren",
            raw={"bt_parcel_info": {"legal_description": "LT A9", "parcel_number": "L2D74"}})
    assert not _eligible(li)


def test_a_negative_result_marker_stays_eligible_here():
    li = _li("GIBSON WALTER CLIFTON III", "437 Quail Ridge Road", county="Warren",
            raw={"bt_parcel_info": {"status": "no_confident_match"}})
    assert _eligible(li)
