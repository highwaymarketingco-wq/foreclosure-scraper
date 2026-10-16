"""ustaxdata.com per-parcel tax search (Robeson County, NC): multi-year bill history.

The row fixtures below are REAL markup, captured live 2026-10-16 from a search on the
board's own parcel_id 021903073 (423 Turkey Branch Rd) -- not reconstructed by hand. The
page's own status-icon legend: bill_open.gif = unpaid, bill_paid.gif = paid, bill_partial.gif
= partially paid.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed
from foreclosure_scraper.enrichment_ustaxdata_tax_search import (
    REJECTED_TENANTS, TENANTS, bill_detail_url, parse_bill_detail, parse_results, search_url,
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


def _page(*rows: str, count: int) -> str:
    return (_HEADER % {"count": count}) + "".join(rows)


def _li(parcel, county="Robeson", raw=None):
    now = datetime.utcnow()
    return Listing(
        source="counties_nc.ustaxdata", source_url="https://x/1",
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
        county=county, state="NC", parcel_id=parcel,
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
    assert bill_detail_url("Alexander", "1004106001", "4166749", 2026) is None


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
