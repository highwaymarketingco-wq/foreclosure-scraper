"""The Ingle Firm (NC) foreclosure scraper — Shapiro & Ingle successor.

Added 2026-06-16. Parses the theinglefirm.com/Sales.aspx docket table
(County | Sale Date | Postponed | Case# | Address | Bid), filtered to the
14 in-scope NC counties. Carries address AND bid amount.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.scrapers.law_firms.ingle_firm import IN_SCOPE, IngleFirm, _money


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
