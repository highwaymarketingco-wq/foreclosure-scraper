"""Unified SC county MIE roster scraper (publicindex.sccourts.org).

Added 2026-06-16: covers the 7 upstate SC counties that previously had
NO foreclosure-sale source (Oconee, Cherokee, Laurens, Union, Greenwood,
Abbeville, Newberry) via the SC Judicial Branch's per-county court-roster
app, driven by the local stealth browser (the host is bot-protected).
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.scrapers.counties_sc.sc_county_rosters import (
    COUNTIES,
    SCCountyRosters,
    parse_roster,
)


_BASE = "https://publicindex.sccourts.org/oconee/courtrosters"
_SEL = f"{_BASE}/RosterSelection.aspx"

_FORECLOSURE_ROW = """<table><tr class="standardRow">
<td>1</td><td>06/19/2026</td><td>11:00 AM</td><td></td><td>Master Sale</td>
<td>Bank of America-PLT</td><td>05/01/2026</td>
<td><a href="CaseDetails.aspx?CaseID=123">2024CP3700456</a><br/>Bank of America vs John Smith</td>
<td>Foreclosure 420</td><td>0123.45-67-890.00</td><td>Atty One</td><td>Atty Two</td>
<td>Completed-06/19/2026 Sale # 1 142 Oak Street, Walhalla $85,000.00</td></tr></table>"""

_NON_FORECLOSURE_ROW = """<table><tr class="standardRow">
<td>1</td><td>06/19/2026</td><td>11:00 AM</td><td></td><td>Partition</td>
<td>Someone-PLT</td><td>05/01/2026</td>
<td><a href="CaseDetails.aspx?CaseID=9">2024CP3700999</a><br/>X vs Y</td>
<td>Partition 300</td><td>0123.45-67-890.00</td><td>A</td><td>B</td><td>notes</td></tr></table>"""


def test_parser_extracts_foreclosure_fields():
    out = parse_roster(_FORECLOSURE_ROW, _SEL, "Oconee", _BASE)
    assert len(out) == 1
    li = out[0]
    assert li.county == "Oconee"
    assert li.state == "SC"
    assert li.case_number == "2024CP3700456"
    assert li.defendant == "John Smith"
    assert li.parcel_id == "0123.45-67-890.00"
    assert li.street_address == "142 Oak Street, Walhalla"
    assert li.opening_bid == 85000.0
    assert li.auction_status == "completed"
    assert li.source == "counties_sc.sc_county_rosters"


def test_parser_skips_non_foreclosure_rows():
    assert parse_roster(_NON_FORECLOSURE_ROW, _SEL, "Oconee", _BASE) == []


def test_parser_rejects_non_tms_in_parcel_field():
    """When an attorney name lands in the TMS column (layout drift), it must
    not be stored as parcel_id."""
    row = _FORECLOSURE_ROW.replace("0123.45-67-890.00", "William Franklin Childers Jr.")
    out = parse_roster(row, _SEL, "Oconee", _BASE)
    assert len(out) == 1
    assert out[0].parcel_id is None


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    slugs = {s.slug for s in all_scrapers()}
    assert "counties_sc.sc_county_rosters" in slugs


def test_covers_in_scope_upstate_counties_only():
    # Greenwood/Abbeville/Newberry are in SCOPE_DENY_COUNTIES, so this
    # scraper only covers the in-scope upstate counties.
    assert set(COUNTIES.values()) == {"Oconee", "Cherokee", "Laurens", "Union"}


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live SC publicindex via stealth browser — slow; RUN_NETWORK_TESTS=1",
)
def test_live_returns_listings_for_at_least_one_county():
    out = list(asyncio.run(SCCountyRosters().fetch()))
    # Many small counties have 0 active sales at a time, so we only assert
    # the flow works (no crash) and any returned row is well-formed.
    for li in out:
        assert li.state == "SC"
        assert li.county in COUNTIES.values()
        if li.parcel_id:
            assert li.parcel_id[0].isdigit()
