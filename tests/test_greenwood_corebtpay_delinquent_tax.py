"""Greenwood County SC CORE/eGov delinquent-tax scraper: table parsing, the
year-suffix parcel-id recovery, and multi-year aggregation.

WHY THESE TESTS EXIST, in one line each:

  * Unlike every other SC tax-roll source in this repo, this portal's "Account
    Number" is NOT stable across tax years for the same parcel — it bakes the
    2-digit tax year onto the end of a stable prefix. `_parcel_prefix()` must
    strip it correctly (verified against real captured multi-year data,
    2026-09-30), or the same house shows up as two/three separate leads and
    the "2+ years delinquent" signal (the strongest distress marker this
    repo's motivated-seller engine looks for) is lost.
  * The search grid's "Amount Due" column is the HISTORICAL bill amount for a
    PAID row, not a current balance — the same label-vs-value trap
    `dorchester_billtrax_delinquent_tax.py` already had to guard against.
    Status must be read from the actual text ("Unpaid"/"Paid"), and a row
    must be BOTH unpaid AND carry a positive amount to become a lead.
  * The search table renders real production markup (tabs/newlines between
    cells, an inline onclick handler, a Font-Awesome icon before the status
    text) — the parser needs to survive that shape, not a hand-cleaned one.

FIXTURES BELOW are taken from LIVE production responses
(greenwoodco.corebtpay.com/egov/apps/bill/pay.egov, captured 2026-09-30), not
hand-built. SMITH_JAMES_M_* is owner "SMITH JAMES M", parcel prefix
"671445000" with three real, currently-unpaid bills (2017/2018/2019) — a
genuine multi-year delinquency. WW_PLASMA_PAID is a real PAID row (owner "WW
PLASMA IV LLC") included to prove the Paid/Unpaid filter actually excludes a
large-dollar row just because its historical Amount Due is nonzero.
DUNLAP_DETAIL_HTML is the real `view=detail` page body for account
688577523500025 (owner "DUNLAP DEBRA SMITH", 137 Patterson Dr, Ninety Six).
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_sc import greenwood_corebtpay_delinquent_tax as mod
from foreclosure_scraper.scrapers.counties_sc.greenwood_corebtpay_delinquent_tax import (
    _aggregate,
    _is_unpaid,
    _parcel_prefix,
    _parse_amount,
    _parse_detail,
    _parse_search_table,
    _sweep,
)

# --- a real search-results table, three years of SMITH JAMES M (parcel
# "671445000") all unpaid, plus one real PAID row for a different owner,
# reproducing the server's actual markup shape verbatim -------------------
SEARCH_TABLE_HTML = """
<table class="eGov_listContent" cellspacing="0" cellpadding="0" border="0" width="100%">
<thead><tr>
<th>View / Pay Bill</th><th>Account</th><th>Tax Year</th>
<th>Name on Account</th><th>Status</th><th>Date Paid</th><th>Amount Due</th>
</tr></thead>
<tbody>
<tr class="eGov_rowOdd">
    <td align="center"><input type="button" name="View &amp; Pay Bill" value="View &amp; Pay Bill" onclick="window.location.href='pay.egov?view=detail;account=67144500019;itemid=1';" /></td>
    <td align="center">67144500019</td>
    <td align="center">2019</td>
    <td align="center">SMITH JAMES M</td>
    <td align="center"><i class="fas fa-times"></i> Unpaid</td>
    <td align="center"></td>
    <td align="center">$ 285.71</td>
</tr>
<tr class="eGov_rowEven">
    <td align="center"><input type="button" name="View &amp; Pay Bill" value="View &amp; Pay Bill" onclick="window.location.href='pay.egov?view=detail;account=67144500018;itemid=1';" /></td>
    <td align="center">67144500018</td>
    <td align="center">2018</td>
    <td align="center">SMITH JAMES M</td>
    <td align="center"><i class="fas fa-times"></i> Unpaid</td>
    <td align="center"></td>
    <td align="center">$ 297.39</td>
</tr>
<tr class="eGov_rowOdd">
    <td align="center"><input type="button" name="View &amp; Pay Bill" value="View &amp; Pay Bill" onclick="window.location.href='pay.egov?view=detail;account=67144500017;itemid=1';" /></td>
    <td align="center">67144500017</td>
    <td align="center">2017</td>
    <td align="center">SMITH JAMES M</td>
    <td align="center"><i class="fas fa-times"></i> Unpaid</td>
    <td align="center"></td>
    <td align="center">$ 328.22</td>
</tr>
<tr class="eGov_rowEven">
    <td align="center"><input type="button" name="View &amp; Pay Bill" value="View &amp; Pay Bill" onclick="window.location.href='pay.egov?view=detail;account=684677012900025;itemid=1';" /></td>
    <td align="center">684677012900025</td>
    <td align="center">2025</td>
    <td align="center">WW PLASMA IV LLC</td>
    <td align="center"><i class="fas fa-check"></i> Paid</td>
    <td align="center">11/17/2025</td>
    <td align="center">$ 43,223.79</td>
</tr>
</tbody>
</table>
"""

DUNLAP_DETAIL_HTML = """
<table>
    <tr><td>Account Number:</td><td>688577523500025</td></tr>
    <tr><td>Account Name:</td><td>DUNLAP DEBRA SMITH</td></tr>
    <tr><td>Service Address:</td><td>137 PATTERSON DR, NINETY, SIX, SC 29666</td></tr>
    <tr><td>Status:</td><td><i class="fas fa-times"></i> Unpaid</td></tr>
    <tr><td>View This Bill:</td><td><a href="https://greenwoodco.corebtpay.com/egov/apps/bill/pay.egov?view=bill;account=688577523500025;id=1;itemid=1">View</a></td></tr>
</table>
"""


def test_parse_amount_strips_dollar_and_commas():
    assert _parse_amount("$ 1,937.04") == 1937.04
    assert _parse_amount("$ 285.71") == 285.71
    assert _parse_amount("") is None
    assert _parse_amount(None) is None
    assert _parse_amount("garbage") is None


def test_is_unpaid_reads_the_text_not_the_icon():
    assert _is_unpaid("Unpaid") is True
    assert _is_unpaid(" Unpaid") is True
    assert _is_unpaid("Paid") is False
    assert _is_unpaid("") is False


def test_parcel_prefix_strips_real_matching_year_suffix():
    """Verified live 2026-09-30: SMITH JAMES M's three bills share stable
    prefix '671445000' with the tax year's last two digits appended."""
    assert _parcel_prefix("67144500019", 2019) == ("671445000", True)
    assert _parcel_prefix("67144500018", 2018) == ("671445000", True)
    assert _parcel_prefix("67144500017", 2017) == ("671445000", True)


def test_parcel_prefix_falls_back_when_suffix_does_not_match_year():
    """A defensive guard: if the last two digits don't actually match this
    row's own tax year, do NOT strip — keep the full account as its own
    parcel id rather than risk grouping unrelated parcels together."""
    assert _parcel_prefix("67144500099", 2019) == ("67144500099", False)


def test_parcel_prefix_refuses_to_strip_too_short_an_id():
    # A 3-4 digit "prefix" after stripping would collide across unrelated
    # parcels constantly — guarded by the len(account) > 4 check.
    assert _parcel_prefix("2519", 2019) == ("2519", False)


def test_parse_search_table_extracts_all_rows():
    rows = _parse_search_table(SEARCH_TABLE_HTML)
    assert len(rows) == 4
    accounts = {r["account"] for r in rows}
    assert accounts == {"67144500019", "67144500018", "67144500017", "684677012900025"}
    unpaid_rows = [r for r in rows if r["unpaid"]]
    assert len(unpaid_rows) == 3
    paid_row = next(r for r in rows if r["account"] == "684677012900025")
    assert paid_row["unpaid"] is False
    assert paid_row["amount"] == 43223.79
    assert paid_row["name"] == "WW PLASMA IV LLC"


def test_parse_search_table_empty_when_no_table_present():
    assert _parse_search_table("<html><body>No results</body></html>") == []


def test_parse_detail_extracts_service_address():
    detail = _parse_detail(DUNLAP_DETAIL_HTML)
    assert detail["account_number"] == "688577523500025"
    assert detail["account_name"] == "DUNLAP DEBRA SMITH"
    assert detail["service_address"] == "137 PATTERSON DR, NINETY, SIX, SC 29666"


def test_multiyear_real_delinquency_aggregates_into_one_listing():
    """The three real SMITH JAMES M bills (parcel '671445000') must collapse
    into ONE listing with all three years and the summed balance — the same
    "don't fragment a multi-year delinquency" requirement
    dorchester_billtrax_delinquent_tax's APPELT test enforces."""
    rows = _parse_search_table(SEARCH_TABLE_HTML)
    listings = _aggregate(rows, detail_by_account={})
    assert len(listings) == 1  # the Paid WW PLASMA row must not surface at all
    li = listings[0]
    assert li.parcel_id == "671445000"
    assert li.owner_name == "SMITH JAMES M"
    assert li.defendant == "SMITH JAMES M"
    assert li.county == "Greenwood"
    assert li.state == "SC"
    assert li.listing_type == ListingType.TAX_LIEN
    assert li.property_kind == PropertyKind.UNKNOWN

    detail = li.raw["greenwood_corebtpay_delinquent_tax"]
    assert detail["years"] == [2017, 2018, 2019]
    assert detail["years_delinquent"] == 3
    assert detail["is_two_year_plus"] is True
    assert detail["total_due"] == round(285.71 + 297.39 + 328.22, 2)
    assert detail["latest_account"] == "67144500019"  # most recent year picked
    assert len(detail["bills"]) == 3

    assert li.raw["tax_owed"]["balance"] == round(285.71 + 297.39 + 328.22, 2)
    assert li.raw["tax_owed"]["kind"] == "delinquent_tax"
    assert li.raw["tax_owed"]["year"] == 2019


def test_aggregate_fills_in_address_from_detail_lookup():
    rows = _parse_search_table(SEARCH_TABLE_HTML)
    detail_map = {"67144500019": {"service_address": "123 TEST RD, GREENWOOD, SC 29646"}}
    listings = _aggregate(rows, detail_by_account=detail_map)
    assert listings[0].street_address == "123 TEST RD, GREENWOOD, SC 29646"


def test_paid_only_search_produces_no_listings():
    rows = _parse_search_table(SEARCH_TABLE_HTML)
    paid_only = [r for r in rows if not r["unpaid"]]
    assert _aggregate(paid_only, detail_by_account={}) == []


# --- _sweep(): the cap-detection / deepening logic -------------------------
# Verified live 2026-09-30 that a real 5,000-row cap exists ("JO" returned
# exactly 5,000; one of its 26 three-letter children, "JOH", alone returned
# 2,817 — proving "JO" was truncated, not genuinely exhausted). These tests
# exercise that deepening logic with PAGE_CAP patched down to a small number
# so the fixtures stay tiny, without needing real network access.

def _make_row_html(account: str, year: int = 2025, name: str = "TEST OWNER",
                    unpaid: bool = True, amount: str = "$ 100.00") -> str:
    # NOTE: account must look like a real one (digits only) — _parse_search_table
    # drops any row whose Account cell doesn't match ^\d+$, the same guard that
    # skips the header row on a real page.
    status = '<i class="fas fa-times"></i> Unpaid' if unpaid else '<i class="fas fa-check"></i> Paid'
    return f"""
<tr>
    <td align="center"><input type="button" /></td>
    <td align="center">{account}</td>
    <td align="center">{year}</td>
    <td align="center">{name}</td>
    <td align="center">{status}</td>
    <td align="center"></td>
    <td align="center">{amount}</td>
</tr>
"""


def _make_table_html(n_rows: int, prefix: str) -> str:
    # The prefix identifies which fake query produced this fixture — encoded in
    # the (free-text) owner NAME field, not the account number, since a real
    # Account Number is numeric-only and _parse_search_table enforces that shape.
    rows = "".join(
        _make_row_html(account=f"9{abs(hash((prefix, i))) % 10**10:010d}",
                       name=f"OWNER FROM PREFIX {prefix} #{i}")
        for i in range(n_rows)
    )
    return f'<table class="eGov_listContent">{rows}</table>'


def test_sweep_deepens_a_capped_prefix_and_discards_the_truncated_read(monkeypatch):
    """A 2-letter prefix that hits PAGE_CAP must be deepened into its 26
    three-letter children, and its own (truncated, unreliable-coverage)
    rows must NOT be kept — only the deepened children's rows should
    survive, even though the capped read technically had real-looking rows
    in it."""
    monkeypatch.setattr(mod, "PAGE_CAP", 3)
    monkeypatch.setattr(mod, "MAX_PREFIX_DEPTH", 3)
    monkeypatch.setattr(mod, "_PACE_S", 0.0)

    calls: list[str] = []

    async def fake_post_search(cli, prefix):
        calls.append(prefix)
        if prefix == "AA":
            return _make_table_html(3, "AA")  # hits the (patched) cap of 3
        if prefix in ("AAB", "AAC"):
            return _make_table_html(1, prefix)
        return "<html><body>no matches</body></html>"

    monkeypatch.setattr(mod, "_post_search", fake_post_search)

    rows, stats = asyncio.run(_sweep(cli=None, prefixes=["AA"], max_requests=100))

    assert "AA" in calls
    assert "AAB" in calls and "AAC" in calls  # deepened into children
    assert stats["capped"] == 1
    # Only the two children's single rows survive — AA's own 3 (truncated,
    # unknown-coverage) rows must be discarded, not unioned in.
    assert len(rows) == 2
    names = {r["name"] for r in rows}
    assert any("PREFIX AAB" in n for n in names)
    assert any("PREFIX AAC" in n for n in names)
    assert not any("PREFIX AA #" in n for n in names)  # AA's own rows excluded


def test_sweep_does_not_deepen_an_uncapped_prefix(monkeypatch):
    monkeypatch.setattr(mod, "PAGE_CAP", 100)
    monkeypatch.setattr(mod, "_PACE_S", 0.0)

    async def fake_post_search(cli, prefix):
        assert prefix == "SM"  # no children should ever be queried
        return _make_table_html(2, "SM")

    monkeypatch.setattr(mod, "_post_search", fake_post_search)

    rows, stats = asyncio.run(_sweep(cli=None, prefixes=["SM"], max_requests=100))
    assert stats["capped"] == 0
    assert len(rows) == 2


def test_sweep_respects_request_budget(monkeypatch):
    monkeypatch.setattr(mod, "_PACE_S", 0.0)
    calls: list[str] = []

    async def fake_post_search(cli, prefix):
        calls.append(prefix)
        return _make_table_html(1, prefix)

    monkeypatch.setattr(mod, "_post_search", fake_post_search)

    rows, stats = asyncio.run(_sweep(cli=None, prefixes=["AA", "AB", "AC", "AD"],
                                     max_requests=2))
    assert stats["requests"] == 2
    assert len(calls) == 2
