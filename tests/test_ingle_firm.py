"""The Ingle Firm (NC) foreclosure scraper — Shapiro & Ingle successor.

Added 2026-06-16. Parses the theinglefirm.com/Sales.aspx docket table
(County | Sale Date | Postponed | Case# | Address | Bid), filtered to the
14 in-scope NC counties. Carries address AND bid amount.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.scrapers.law_firms.ingle_firm import (
    IN_SCOPE,
    IngleFirm,
    _money,
    _parse_html,
)

_TABLE_HEAD = (
    "<table><tr><th>County</th><th>Original Sale Date/Time</th>"
    "<th>Postponed Until Date/Time</th><th>Court Case Number</th>"
    "<th>Property Address</th><th>Bid Amount</th></tr>"
)


def test_money_parses_bid():
    assert _money("$562,853.00") == 562853.0
    assert _money("150000") == 150000.0
    assert _money("") is None
    assert _money("$0.00") is None


def test_in_scope_excludes_denied_counties():
    # 11 in-scope NC counties; Mecklenburg/Madison/Yancey are denied.
    assert len(IN_SCOPE) == 11
    assert "rutherford" in IN_SCOPE and "buncombe" in IN_SCOPE
    assert "mecklenburg" not in IN_SCOPE  # denied (Charlotte)
    assert "madison" not in IN_SCOPE and "yancey" not in IN_SCOPE
    # Ashe / Cabarrus appear in the table but are out of scope.
    assert "ashe" not in IN_SCOPE and "cabarrus" not in IN_SCOPE


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "law_firms.ingle_firm" in {s.slug for s in all_scrapers()}


def test_out_of_state_county_name_collision_excluded():
    """This is a multi-state docket (live 2026-10-01 pull mixed in Talladega,
    AL rows alongside NC). Several in-scope NC county NAMES also exist as real
    counties in other states this firm covers (Rutherford County TN, Polk
    County GA/TN, Lincoln County GA/TN/MS) — matching on the bare county name
    without checking the cell's own state suffix would silently relabel an
    out-of-state property as a North Carolina lead."""
    html = _TABLE_HEAD + (
        "<tr><td>Rutherford, TN</td><td>9/24/26 11:00 AM</td><td></td>"
        "<td>26-CV-900</td><td>100 Main St, Murfreesboro, TN 37130</td>"
        "<td>$50,000.00</td></tr>"
        "<tr><td>Rutherford, NC</td><td>12/3/25 12:00 PM</td><td></td>"
        "<td>25SP000020-800</td>"
        "<td>1530 Painters Gap Rd, Union Mills, NC 28167</td>"
        "<td>$125,533.76</td></tr></table>"
    )
    out = _parse_html(html, "law_firms.ingle_firm")
    assert len(out) == 1
    assert out[0].state == "NC"
    assert out[0].street_address == "1530 Painters Gap Rd"


def test_legacy_county_cell_with_no_state_suffix_still_matches():
    html = _TABLE_HEAD + (
        "<tr><td>Rutherford</td><td>12/3/25 12:00 PM</td><td></td>"
        "<td>25SP000020-800</td>"
        "<td>1530 Painters Gap Rd, Union Mills, NC 28167</td>"
        "<td>$125,533.76</td></tr></table>"
    )
    out = _parse_html(html, "law_firms.ingle_firm")
    assert len(out) == 1
    assert out[0].county == "Rutherford"


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live theinglefirm.com — set RUN_NETWORK_TESTS=1",
)
def test_live_returns_in_scope_nc_with_address():
    out = list(asyncio.run(IngleFirm().fetch()))
    for li in out:
        assert li.state == "NC"
        assert li.county.lower() in IN_SCOPE
        assert li.case_number  # NC SP docket number
