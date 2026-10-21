"""ustaxdata.com per-parcel tax search (Robeson County, NC): multi-year bill history.

The row fixtures below are REAL markup, captured live 2026-10-16 from a search on the
board's own parcel_id 021903073 (423 Turkey Branch Rd) -- not reconstructed by hand. The
page's own status-icon legend: bill_open.gif = unpaid, bill_paid.gif = paid, bill_partial.gif
= partially paid.
"""
from __future__ import annotations

from datetime import datetime

import asyncio

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed
from foreclosure_scraper.enrichment_ustaxdata_tax_search import (
    NAME_SEARCH_TENANTS, REJECTED_TENANTS, TENANTS, _confirm_by_address, bill_detail_url,
    enrich_ustaxdata, parse_bill_detail, parse_results, search_url, search_url_by_name,
)

#: One real row (2026, paid), verbatim from the live page, plus the page chrome
#: parse_results() actually looks at ("N Records Found" / the absence of the 0-record text).
_HEADER = """
<td width="865" valign="middle" class="a1"><font color="#336699"><strong>
<font color="#3333CC">%(count)s</font></strong> Records
Found Matching your criteria <strong> 021903073 </strong><br>
"""

_ROW_2026_PAID = """
                <tr valign="middle" class="style16">
                  <td height="17" align="center" valign="middle" bgcolor="E6FADE">1&nbsp;</td>
                  <td align="center" valign="middle" bgcolor="E6FADE"><font color="#000000">2026</font></td>
                  <td align="center" valign="middle" bgcolor="E6FADE"><div align="center" class="a1"><font color="#000000"><a href="account.cfm?parcelID=021903073                ">1004106001   </a></font></div></td>
                  <td valign="middle"  bgcolor="E6FADE"><div align="center">
                    <p align="center" class="a1"><font color="#000000">4166749</font></p>
                    </div>                  </td>
                  <td align="center" bgcolor="E6FADE"><font color="#000000">BALDWIN RODERICK LEVERNE </font><font color="#FF0000"><strong></strong></font></td>
                  <td align="center" bgcolor="E6FADE"><font color="#000000">> CONTACT COUNTY FOR</font></td>
                  <td align="center" bgcolor="E6FADE"><font color="#000000">

                      <img src="images/bill_paid.gif">

                  </font></td>
                  <td align="center" bgcolor="E6FADE"><font color="#000000">$94,600.00</font></td>
                  <td align="center" bgcolor="E6FADE"><div align="center"><a href="taxbill.cfm?ownerID=1004106001&billNo=4166749&TaxYear=2026" onClick="NewWindow(this.href,'name','690','560','yes');return false;"><img src="images/view_taxBilla.gif" alt="View Tax Bill" name="Image12" width="69" height="15" border="0"></a></div>                  </td>
                  <td align="center" bgcolor="E6FADE"><div align="center"><a href="transhistory.cfm?ownerID=1004106001   " onClick="NewWindow(this.href,'name','690','350','yes');return false;"><img src="images/view_transhistorya.gif" alt="View Transaction History" name="Image13" width="100" height="15" border="0"></a></div>                  </td>
                </tr>
"""

_ROW_2023_PAID = """
                <tr valign="middle" class="style16">
                  <td height="17" align="center" valign="middle" bgcolor="FFFFFF">4&nbsp;</td>
                  <td align="center" valign="middle" bgcolor="FFFFFF"><font color="#000000">2023</font></td>
                  <td align="center" valign="middle" bgcolor="FFFFFF"><div align="center" class="a1"><font color="#000000"><a href="account.cfm?parcelID=021903073                ">1004106001   </a></font></div></td>
                  <td valign="middle"  bgcolor="FFFFFF"><div align="center">
                    <p align="center" class="a1"><font color="#000000">3850190</font></p>
                    </div>                  </td>
                  <td align="center" bgcolor="FFFFFF"><font color="#000000">BALDWIN RODERICK LEVERNE </font><font color="#FF0000"><strong></strong></font></td>
                  <td align="center" bgcolor="FFFFFF"><font color="#000000">> CONTACT COUNTY FOR</font></td>
                  <td align="center" bgcolor="FFFFFF"><font color="#000000">

                      <img src="images/bill_paid.gif">

                  </font></td>
                  <td align="center" bgcolor="FFFFFF"><font color="#000000">$74,700.00</font></td>
                  <td align="center" bgcolor="FFFFFF"><div align="center"><a href="taxbill.cfm?ownerID=1004106001&billNo=3850190&TaxYear=2023" onClick="NewWindow(this.href,'name','690','560','yes');return false;"><img src="images/view_taxBilla.gif" alt="View Tax Bill" name="Image12" width="69" height="15" border="0"></a></div>                  </td>
                  <td align="center" bgcolor="FFFFFF"><div align="center"><a href="transhistory.cfm?ownerID=1004106001   " onClick="NewWindow(this.href,'name','690','350','yes');return false;"><img src="images/view_transhistorya.gif" alt="View Transaction History" name="Image13" width="100" height="15" border="0"></a></div>                  </td>
                </tr>
"""

#: Zero-match page, same vendor/template, verbatim text that trips a real 0-record search
#: (captured live against Alexander/Rockingham with the board's own, wrong-for-them parcel_id).
_ZERO_RECORDS_PAGE = """
<td width="865" valign="middle" class="a1"><font color="#336699"><strong>
<font color="#3333CC">0</font></strong> Records
Found Matching your criteria <strong> 3736984870 </strong><br>
"""

#: taxbill.cfm detail page for the SAME real 2026/paid bill, verbatim (trimmed), captured
#: live 2026-10-16: the gross year levy ("Amount Taxed") and what's actually outstanding
#: today ("TOTAL AMOUNT OWED") are two separate figures, $0.00 here because this bill is paid.
_DETAIL_PAID = """
        <TD colspan="2" class="Taxbill_white"><table width="100%" border="0" cellspacing="0" cellpadding="2">
            <tr>
              <td width="60%"><div align="left" class="smallT1">> CONTACT COUNT</div></td>
              <td width="40%">
                <div align="left" class="smallT1">$ 974.73</div></td>
            </tr>
          </table>
        </TD>
        </TR>
    </TABLE>
        <table width="100%" height="16" border="0" cellpadding="0" cellspacing="0">
      <tr>
        <td width="80%" valign="middle"><div align="right"><font size="2"><strong><span class="style8">TOTAL
                  AMOUNT OWED:</span></strong></font></div></td>
        <td width="2%" valign="middle"><img src="images/arrow.gif" width="5" height="8"></td>
        <td width="18%" valign="middle"><div align="center"><font color="#FF0000" size="3"><strong><span class="style10">$ 0.00</span></strong></font>&nbsp;</div></td>
        </tr>
"""

#: Same real markup shape, the dollar figure swapped for a genuinely-owed amount (no live
#: delinquent Robeson bill was captured to test against, so this value is substituted --
#: same convention as test_bt_appraisal_card.py's REAL_CARD mutations).
_DETAIL_UNPAID = _DETAIL_PAID.replace("$ 0.00", "$ 410.22")


#: Rockingham's taxbill.cfm detail page, REAL markup (trimmed), captured live 2026-10-20 against
#: parcel 1339306 / bill 3681429 / TaxYear 2026 (owner KNOWLES CAROL FAYE/CHAD BRISON, 3327
#: Grooms Rd -- a real board row, found via the already-shipped NAME_SEARCH_TENANTS chain). This
#: is the bug fixture: Rockingham's label is "TOTAL<newline>DUE" (no colon, unlike Robeson's
#: "TOTAL AMOUNT OWED:"), and its value cell carries NO "$" prefix at all on a nonzero amount --
#: the original _OWED_RE (tuned to Robeson's "TOTAL AMOUNT OWED:...\$" shape) matched neither
#: piece, so every Rockingham bill's total_due/balance stayed empty even on a confirmed unpaid
#: bill. Also real: no separate "Amount Taxed" field exists on this template at all (the three
#: address/amount pairs above are individual line-item charges that sum to TOTAL DUE, not a
#: single gross-levy figure) -- amount_taxed is correctly absent for this tenant, not a bug.
_DETAIL_ROCKINGHAM_UNPAID = """
	  <TD colspan="2" class="Taxbill_white"><table width="100%" border="0" cellspacing="0" cellpadding="2">
            <tr>
              <td width="52%"><div align="left" class="smallT1">3327 GROOMS RD           </div></td>
              <td width="48%">
                <div align="left" class="smallT1">$ 43.13</div></td>
            </tr>
          </table><table width="100%" border="0" cellspacing="0" cellpadding="2">
            <tr>
              <td width="52%"><div align="left" class="smallT1">3327 GROOMS RD           </div></td>
              <td width="48%">
                <div align="left" class="smallT1">$ 62.58</div></td>
            </tr>
          </table><table width="100%" border="0" cellspacing="0" cellpadding="2">
            <tr>
              <td width="52%"><div align="left" class="smallT1">3327 GROOMS RD           </div></td>
              <td width="48%">
                <div align="left" class="smallT1">$ 57.80</div></td>
            </tr>
          </table>
	    <div align="center"></div></TD>
   		</TR>
        <tr>
          <td>
            </td>
          <TD valign="middle" bgcolor="#FF0000" class="redbox"><div align="center" class="style10">TOTAL
          DUE </div></TD>
          <TD valign="middle" bgcolor="#FF0000" class="redbox"><div align="center" class="style3">163.51</div></TD>
        </tr>
      </table>
"""

#: Same real tenant/account, a PAID year (bill 3650745 / TaxYear 2025) -- captured live
#: 2026-10-20. Here the vendor DOES prefix the zero amount with "$", confirming the "$" prefix
#: is simply inconsistent per-value on this template, not a reliable signal either way.
_DETAIL_ROCKINGHAM_PAID = """
          <TD valign="middle" bgcolor="#FF0000" class="redbox"><div align="center" class="style10">TOTAL
          DUE </div></TD>
          <TD valign="middle" bgcolor="#FF0000" class="redbox"><div align="center" class="style3">$ 0.00</div></TD>
"""


#: Real row, captured live 2026-10-16 on alexander.ustaxdata.com?lastName=RHYNE&firstName=
#: DENNIS (REJECTED_TENANTS' own documented probe) -- the row's cells[5] carries a REAL street
#: address here, unlike Robeson's "> CONTACT COUNTY FOR" placeholder at the same position
#: (confirmed live on both the same day: this is a genuine per-tenant difference, not a parcel-
#: search-vs-name-search structural one -- Rockingham's own name-search rows also carry a real
#: address in this same column, just street-name-only on the one sampled, no house number).
_ROW_ALEXANDER_RHYNE = """
                <tr valign="middle" class="style16">
                  <td height="17" align="center" valign="middle" bgcolor="E6FADE">1&nbsp;</td>
                  <td align="center" valign="middle" bgcolor="E6FADE"><font color="#000000">2026</font></td>
                  <td align="center" valign="middle" bgcolor="E6FADE"><div align="center" class="a1"><font color="#000000"><a href="account.cfm?parcelID=0002451 ">0202921 </a></font></div></td>
                  <td valign="middle"  bgcolor="E6FADE"><div align="center">
                    <p align="center" class="a1"><font color="#000000">2218297</font></p>
                    </div>                  </td>
                  <td align="center" bgcolor="E6FADE"><font color="#000000">RHYNE DENNIS W & / RHYNE JULI...</font><font color="#FF0000"><strong></strong></font></td>
                  <td align="center" bgcolor="E6FADE"><font color="#000000">&nbsp;&nbsp;5195 RINK DAM RD </font></td>
                  <td align="center" bgcolor="E6FADE"><font color="#000000">
                      <img src="images/bill_open.gif">
                  </font></td>
                  <td align="center" bgcolor="E6FADE"><font color="#000000">$ 170.13</font></td>
                  <td align="center" bgcolor="E6FADE"><div align="center"><a href="taxbill.cfm?ownerID=0202921&billNo=2218297&TaxYear=2026" onClick="NewWindow(this.href,'name','690','560','yes');return false;"><img src="images/view_taxBilla.gif" alt="View Tax Bill" name="Image12" width="69" height="15" border="0"></a></div>                  </td>
                  <td align="center" bgcolor="E6FADE"><div align="center"><a href="transhistory.cfm?ownerID=0202921 " onClick="NewWindow(this.href,'name','690','350','yes');return false;"><img src="images/view_transhistorya.gif" alt="View Transaction History" name="Image13" width="100" height="15" border="0"></a></div>                  </td>
                </tr>
"""

#: Same shape, a second, DIFFERENT account at the SAME searched-on address -- for the "name
#: search is ambiguous between two people" safety test (two owners sharing a mailing/situs
#: string is a real vendor-data-quality shape, not a contrived one: see Berkeley's own joint-
#: owner "/ " convention above). Invented account/bill numbers, same vendor markup.
_ROW_ALEXANDER_RHYNE_OTHER = _ROW_ALEXANDER_RHYNE.replace("0202921", "0299999").replace("2218297", "2299999")


def _page(*rows: str, count: int) -> str:
    return (_HEADER % {"count": count}) + "".join(rows)


def _li(parcel=None, county="Robeson", raw=None, owner_name=None, street_address=None):
    now = datetime.utcnow()
    return Listing(
        source="counties_nc.ustaxdata", source_url="https://x/1",
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
        county=county, state="NC", parcel_id=parcel, owner_name=owner_name,
        street_address=street_address,
        first_seen=now, last_seen=now, raw=raw or {})


# ---------------------------------------------------------------------------
# search_url: only the verified tenant, the board's own parcel_id as-is
# ---------------------------------------------------------------------------

def test_only_robeson_is_wired():
    assert list(TENANTS) == ["Robeson"]
    assert "Alexander" in REJECTED_TENANTS and "Rockingham" in REJECTED_TENANTS


def test_url_uses_the_boards_parcel_id_unmodified():
    url = search_url("Robeson", "021903073")
    assert url.startswith("https://www.ustaxdata.com/nc/robeson/Robesontaxlist.cfm?")
    assert "parcelNum=021903073" in url


def test_county_match_is_case_and_suffix_insensitive():
    assert search_url("robeson", "1") == search_url("ROBESON County", "1")


def test_an_unwired_county_yields_no_url_rather_than_a_guess():
    """Alexander/Rockingham are the same vendor but key on a different id than the board
    carries (module docstring) -- silently querying them would hit the wrong account."""
    assert search_url("Alexander", "3736984870") is None
    assert search_url("Rockingham", "792800687243") is None


def test_a_blank_parcel_yields_no_url():
    assert search_url("Robeson", "") is None
    assert search_url("Robeson", None) is None


# ---------------------------------------------------------------------------
# parse_results: real captured markup
# ---------------------------------------------------------------------------

def test_a_real_paid_row_parses_every_field():
    rows = parse_results(_page(_ROW_2026_PAID, count=13))
    assert len(rows) == 1
    row = rows[0]
    assert row["year"] == row["tax_year"] == 2026
    assert row["account"] == "1004106001"
    assert row["bill_no"] == "4166749"
    assert row["owner_name"] == "BALDWIN RODERICK LEVERNE"
    assert row["status"] == "paid"
    assert row["taxable_value"] == 94600.0


def test_multiple_years_parse_in_page_order():
    rows = parse_results(_page(_ROW_2026_PAID, _ROW_2023_PAID, count=13))
    assert [r["year"] for r in rows] == [2026, 2023]
    assert rows[1]["taxable_value"] == 74700.0


def test_an_unpaid_status_icon_is_read_correctly():
    """Only a paid parcel was captured live; the unpaid/partial path is the same markup
    position with a different icon filename (the page's own legend), substituted here."""
    unpaid = _ROW_2026_PAID.replace("images/bill_paid.gif", "images/bill_open.gif")
    partial = _ROW_2023_PAID.replace("images/bill_paid.gif", "images/bill_partial.gif")
    rows = parse_results(_page(unpaid, partial, count=13))
    assert rows[0]["status"] == "unpaid"
    assert rows[1]["status"] == "partial"


def test_zero_records_yields_no_rows_not_a_crash():
    assert parse_results(_ZERO_RECORDS_PAGE) == []


def test_junk_input_yields_no_rows():
    assert parse_results("") == []
    assert parse_results("<html>server error</html>") == []


# ---------------------------------------------------------------------------
# parse_bill_detail / bill_detail_url: the second hop, real dollar amounts
# ---------------------------------------------------------------------------

def test_detail_url_is_one_path_segment_up_from_the_search_page():
    url = bill_detail_url("Robeson", "1004106001", "4166749", 2026)
    assert url == ("https://www.ustaxdata.com/nc/robeson/taxbill.cfm"
                   "?ownerID=1004106001&billNo=4166749&TaxYear=2026")


def test_detail_url_needs_every_piece():
    assert bill_detail_url("Robeson", None, "4166749", 2026) is None
    assert bill_detail_url("Robeson", "1004106001", None, 2026) is None
    assert bill_detail_url("Robeson", "1004106001", "4166749", None) is None
    # Not Transylvania: it's neither a parcel-id tenant (TENANTS) nor a name-search tenant
    # (NAME_SEARCH_TENANTS) -- unlike Alexander, which is the latter since the 2026-10-16
    # name-search fix (see test_name_search_tenants.py).
    assert bill_detail_url("Transylvania", "1004106001", "4166749", 2026) is None


def test_a_paid_bills_detail_reads_zero_owed_and_the_gross_levy():
    got = parse_bill_detail(_DETAIL_PAID)
    assert got["amount_owed"] == 0.0
    assert got["amount_taxed"] == 974.73


def test_an_unpaid_bills_detail_reads_the_real_balance():
    """Same page shape, a real outstanding figure instead of $0.00 -- this is the number
    enrich_ustaxdata sums into raw['ustaxdata_delinquent_tax']['balance']."""
    got = parse_bill_detail(_DETAIL_UNPAID)
    assert got["amount_owed"] == 410.22


def test_detail_junk_input_yields_nothing():
    assert parse_bill_detail("") == {}
    assert parse_bill_detail("<html>server error</html>") == {}


# ---------------------------------------------------------------------------
# Rockingham's detail-page template (2026-10-20 fix): "TOTAL DUE" (no colon), value cell with
# no "$" prefix on a nonzero amount -- the original Robeson-only _OWED_RE matched neither piece,
# so Rockingham's balance stayed empty even on a confirmed, fetched, unpaid bill. Robeson's own
# tests above (test_a_paid_bills_detail_reads_zero_owed_and_the_gross_levy etc.) must still pass
# unchanged -- this extends the pattern, it does not replace it.
# ---------------------------------------------------------------------------

def test_rockinghams_total_due_label_and_unprefixed_amount_are_read():
    """Real bug fixture: live Rockingham parcel 1339306/bill 3681429/2026, $163.51 unpaid
    across 3 line-item charges, no Amount Taxed field on this template at all."""
    got = parse_bill_detail(_DETAIL_ROCKINGHAM_UNPAID)
    assert got["amount_owed"] == 163.51
    assert "amount_taxed" not in got


def test_rockinghams_paid_bill_reads_zero_even_with_a_dollar_sign():
    """Same label, same real account, a paid year -- the vendor's own $ prefix is inconsistent
    per-value on this template (present here, absent on the unpaid fixture above), so the fix
    must not depend on it either way."""
    got = parse_bill_detail(_DETAIL_ROCKINGHAM_PAID)
    assert got["amount_owed"] == 0.0


def test_robesons_detail_template_still_parses_after_the_rockingham_fix():
    """Regression guard: extending _OWED_RE to also match Rockingham's "TOTAL DUE" label must
    not disturb Robeson's own "TOTAL AMOUNT OWED:" match (the two live fixtures already covered
    above by test_a_paid_bills_detail_reads_zero_owed_and_the_gross_levy /
    test_an_unpaid_bills_detail_reads_the_real_balance -- re-asserted together here as the
    single before/after regression check for this fix)."""
    assert parse_bill_detail(_DETAIL_PAID)["amount_owed"] == 0.0
    assert parse_bill_detail(_DETAIL_PAID)["amount_taxed"] == 974.73
    assert parse_bill_detail(_DETAIL_UNPAID)["amount_owed"] == 410.22


# ---------------------------------------------------------------------------
# Downstream: enrich_tax_owed must pick this block up with no extra wiring
# ---------------------------------------------------------------------------

def test_a_multi_year_unpaid_block_feeds_tax_owed_and_aging_generically():
    """The whole point of the block shape (a top-level balance from the real detail-page
    read, a tax-ish block name): no per-source registration needed in enrichment_tax_owed.
    py's _SOURCES -- Pass B's generic scan (which gates on this balance, not the years list
    alone) and unpaid_levy_years() pick it up the same way qpaybill_roll's blocks do."""
    li = _li("021903073", raw={"ustaxdata_delinquent_tax": {
        "bills": [
            {"year": 2026, "tax_year": 2026, "total_due": 0.0},
            {"year": 2025, "tax_year": 2025, "total_due": 410.22},
            {"year": 2024, "tax_year": 2024, "total_due": 398.10},
        ],
        "years_unpaid": [2024, 2025],
        "balance": 808.32, "total_due": 808.32,
        "taxpayer_of_record": "BALDWIN RODERICK LEVERNE",
        "assessed_value": 94600.0,
        "source_url": "https://x",
    }})
    stats = enrich_tax_owed([li])
    assert stats["stamped"] == 1
    assert li.raw["tax_owed"]["balance"] == 808.32
    assert li.raw["tax_owed"]["kind"] == "delinquent_tax"
    assert li.raw["tax_owed"]["years_delinquent"] == 2


def test_a_no_record_block_is_inert():
    """status=no_record carries no amount key, so Pass B must not mistake it for a claim."""
    li = _li("021903073", raw={"ustaxdata_delinquent_tax": {
        "status": "no_record", "source_url": "https://x", "checked_at": "2026-10-16T00:00:00"}})
    stats = enrich_tax_owed([li])
    assert stats["stamped"] == 0
    assert "tax_owed" not in li.raw


# ---------------------------------------------------------------------------
# NAME_SEARCH_TENANTS (2026-10-16): Alexander/Rockingham's board parcel_id doesn't match this
# vendor's own account numbering (REJECTED_TENANTS), but the search form's separate lastName/
# firstName/businessName fields reach the real account by name instead -- trusted only once a
# result's own situs address_relation()-matches the board's street_address.
# ---------------------------------------------------------------------------

async def _no_sleep(*_a, **_k) -> None:
    return None


def test_search_url_by_name_splits_a_person_and_keeps_a_business_whole():
    url = search_url_by_name("Alexander", "RHYNE DENNIS W")
    assert "lastName=RHYNE" in url and "firstName=DENNIS" in url
    assert url.startswith(NAME_SEARCH_TENANTS["Alexander"] + "?")

    url2 = search_url_by_name("Rockingham", "BMS INVESTMENT PROPERTIES LLC")
    assert "businessName=BMS" in url2.replace("+", " ") or "businessName=BMS+INVESTMENT" in url2


def test_search_url_by_name_is_none_without_a_usable_name_or_tenant():
    assert search_url_by_name("Alexander", None) is None
    assert search_url_by_name("Alexander", "") is None
    assert search_url_by_name("Robeson", "RHYNE DENNIS") is None   # a parcel-id tenant, not this one


def test_parse_results_reads_the_real_situs_alongside_everything_else():
    rows = parse_results(_page(_ROW_ALEXANDER_RHYNE, count=15))
    assert rows[0]["situs"] == "5195 RINK DAM RD"
    assert rows[0]["account"] == "0202921" and rows[0]["status"] == "unpaid"


def test_parse_results_situs_is_the_raw_cell_even_on_robesons_placeholder():
    """parse_results is a dumb extractor: Robeson's "> CONTACT COUNTY FOR" at the same column
    position (the existing, already-documented Asset-Description placeholder, not an address)
    comes through verbatim. It's _confirm_by_address's job, via address_relation's "unknown"
    verdict on a value with no usable house number, to never treat this as a match -- tested
    separately below, not here."""
    rows = parse_results(_page(_ROW_2026_PAID, count=1))
    assert rows[0]["situs"] == "> CONTACT COUNTY FOR"
    assert _confirm_by_address(rows, "423 Turkey Branch Rd") is None


def test_confirm_by_address_matches_the_one_account_whose_situs_agrees():
    bills = parse_results(_page(_ROW_ALEXANDER_RHYNE, count=1))
    assert _confirm_by_address(bills, "5195 Rink Dam Rd") == "0202921"


def test_confirm_by_address_refuses_to_guess_between_two_different_accounts():
    """Two different people sharing a searched name must never be resolved by picking either
    one -- the whole reason this function exists instead of trusting the first row."""
    bills = parse_results(_page(_ROW_ALEXANDER_RHYNE, _ROW_ALEXANDER_RHYNE_OTHER, count=2))
    assert len({b["account"] for b in bills}) == 2
    assert _confirm_by_address(bills, "5195 Rink Dam Rd") is None


def test_confirm_by_address_declines_a_street_name_with_no_house_number():
    """address_relation() calls this "unknown", not "match" -- Rockingham's own live BMS
    INVESTMENT row carries exactly this shape ("SPEARMAN RD", no number); the safe behavior is
    to never confirm it automatically, not to guess."""
    bills = [{"account": "1326686", "situs": "SPEARMAN RD"}]
    assert _confirm_by_address(bills, "SPEARMAN RD") is None


def test_confirm_by_address_is_none_on_no_bills_or_no_board_address():
    assert _confirm_by_address([], "5195 Rink Dam Rd") is None
    bills = parse_results(_page(_ROW_ALEXANDER_RHYNE, count=1))
    assert _confirm_by_address(bills, None) is None


def test_enrich_ustaxdata_name_search_end_to_end(monkeypatch):
    """The real Alexander case this whole fix is for: a board row with no usable parcel_id
    match for this vendor, found instead by name and confirmed by address, feeding the same
    ustaxdata_delinquent_tax block shape the parcel-id path already produces."""
    import httpx

    class _Resp:
        def __init__(self, text):
            self.text, self.status_code = text, 200

        def raise_for_status(self):
            pass

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, *a, **k):
            if "taxbill.cfm" in url:
                return _Resp(_DETAIL_UNPAID)
            return _Resp(_page(_ROW_ALEXANDER_RHYNE, count=15))

    import foreclosure_scraper.enrichment_ustaxdata_tax_search as mod
    monkeypatch.setattr(mod.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    li = _li(parcel=None, county="Alexander", owner_name="RHYNE DENNIS W",
             street_address="5195 Rink Dam Rd")
    stats = asyncio.run(enrich_ustaxdata([li]))

    assert stats["name_search_confirmed"] == 1 and stats["name_search_unconfirmed"] == 0
    block = li.raw["ustaxdata_delinquent_tax"]
    assert block["bills"][0]["account"] == "0202921"
    assert block["taxpayer_of_record"] == "RHYNE DENNIS W & / RHYNE JULI..."
    # 2026-10-20 Rockingham backfill bug: tax_binding.bind_block() needs a top-level address
    # field (BLOCK_ADDRESS_FIELDS) to bind this block to the row -- the confirmed address this
    # module already verified (_confirm_by_address, above) must actually land in the block, or
    # every confirmed hit gets scrubbed as "no_evidence" on the very next enrich_tax_owed() call
    # (see test_a_confirmed_name_search_block_survives_enrich_tax_owed below).
    assert block["situs"] == "5195 RINK DAM RD"


def test_a_confirmed_name_search_block_survives_enrich_tax_owed(monkeypatch):
    """THE BUG (2026-10-20, Rockingham backfill dry-run: 1,053 checked, 0 confirmed). enrich_
    ustaxdata() genuinely confirms a real address match before trusting a name-search hit, but
    never used to stamp that address onto the block -- so tax_binding.bind_block() had no
    parcel id (this vendor's own account never matches the board's parcel_id format, the whole
    reason this module name-searches at all), no address, and no own-source match (the row's
    source is whatever originally found it, e.g. liensnc, not this enrichment), and fell
    through to "no_evidence" -- scrub_unbound_tax() then removed the block on the very next
    enrich_tax_owed() call, the SAME call the real pipeline always makes (Pass 0 runs before
    the balance is ever read). Fixed by stamping the already-confirmed situs onto the block
    under a BLOCK_ADDRESS_FIELDS key ("situs"); this test runs the real two-function chain
    (not just bind_block in isolation) the way the backfill script does."""
    import httpx

    class _Resp:
        def __init__(self, text):
            self.text, self.status_code = text, 200

        def raise_for_status(self):
            pass

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, *a, **k):
            if "taxbill.cfm" in url:
                return _Resp(_DETAIL_UNPAID)
            return _Resp(_page(_ROW_ALEXANDER_RHYNE, count=15))

    import foreclosure_scraper.enrichment_ustaxdata_tax_search as mod
    monkeypatch.setattr(mod.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    li = _li(parcel=None, county="Alexander", owner_name="RHYNE DENNIS W",
             street_address="5195 Rink Dam Rd")
    asyncio.run(enrich_ustaxdata([li]))
    assert "ustaxdata_delinquent_tax" in li.raw   # the enrichment did its job

    stats = enrich_tax_owed([li])
    assert stats["unbound"]["rows_scrubbed"] == 0
    assert stats["unbound"]["by_reason"] == {}
    assert "ustaxdata_delinquent_tax" in li.raw   # not scrubbed as "no_evidence"
    assert li.raw["tax_owed"]["balance"] == 410.22   # Pass B now gets a chance to read it


def test_enrich_ustaxdata_name_search_unconfirmed_does_not_fabricate_a_match(monkeypatch):
    """A real result set with no address-confirmed account must stamp "unconfirmed", not
    silently adopt the first (possibly wrong-person) row."""
    import httpx

    class _Resp:
        def __init__(self, text):
            self.text, self.status_code = text, 200

        def raise_for_status(self):
            pass

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, *a, **k):
            return _Resp(_page(_ROW_ALEXANDER_RHYNE, count=15))

    import foreclosure_scraper.enrichment_ustaxdata_tax_search as mod
    monkeypatch.setattr(mod.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    li = _li(parcel=None, county="Alexander", owner_name="RHYNE DENNIS W",
             street_address="999 Nowhere Near It Dr")
    stats = asyncio.run(enrich_ustaxdata([li]))

    assert stats["name_search_unconfirmed"] == 1 and stats["name_search_confirmed"] == 0
    assert li.raw["ustaxdata_delinquent_tax"]["status"] == "name_search_unconfirmed"


def test_bill_detail_url_now_resolves_for_a_name_search_tenant():
    url = bill_detail_url("Alexander", "0202921", "2218297", 2026)
    assert url == "https://alexander.ustaxdata.com/taxbill.cfm?ownerID=0202921&billNo=2218297&TaxYear=2026"
