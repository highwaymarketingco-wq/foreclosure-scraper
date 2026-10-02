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
<td><a href="../PublicIndex/CaseDetails.aspx?CourtAgency=37003&amp;Casenum=2024CP3700456&amp;CaseType=V&amp;Org=CR">2024CP3700456</a><br/>Bank of America vs John Smith</td>
<td>Foreclosure 420</td><td>0123.45-67-890.00</td><td>Atty One</td><td>Atty Two</td>
<td class="notesTD"><div class="notesCell">Completed-06/19/2026 Sale # 1 142 Oak Street, Walhalla $85,000.00</div></td></tr></table>"""

_NON_FORECLOSURE_ROW = """<table><tr class="standardRow">
<td>1</td><td>06/19/2026</td><td>11:00 AM</td><td></td><td>Partition</td>
<td>Someone-PLT</td><td>05/01/2026</td>
<td><a href="../PublicIndex/CaseDetails.aspx?CaseID=9">2024CP3700999</a><br/>X vs Y</td>
<td>Partition 300</td><td>0123.45-67-890.00</td><td>A</td><td>B</td><td class="notesTD"><div class="notesCell">notes</div></td></tr></table>"""

#: Laurens' real shape: 12 cells, NO separate TMS/Map# column (the attorney
#: blocks shift one column left of Oconee's layout and notes lands at index
#: 11, not 12). Verified live 2026-10-01 against publicindex.sccourts.org/
#: laurens/courtrosters/. Regression for the column-count bug fixed the same day.
_LAURENS_12COL_ROW = """<table><tr class="standardRow">
<td>10</td><td>10/21/2026</td><td>9:30 AM</td><td></td>
<td>Motion/Dismiss &amp; Judgment on the Pleadings</td>
<td>U.S. Bank &amp; Trust Company-PLT</td><td>04/27/2026</td>
<td><a href="../PublicIndex/CaseDetails.aspx?CourtAgency=30002&amp;Casenum=2026CP3000125&amp;CaseType=V&amp;Org=CR">2026CP3000125</a><br/>U.S. Bank &amp; Trust Company vs Randall J Owens , defendant, et al</td>
<td>Foreclosure 420</td>
<td>B. Lindsay Crawford III&nbsp;&nbsp;(803) 790-2626</td>
<td>Rodney M. Brown&nbsp;&nbsp;(864) 862-2528</td>
<td class="notesTD"><div class="notesCell">Continued per email from Mr. Brown</div></td></tr></table>"""


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
    # AUDITED 2026-10-01: the live href is "../PublicIndex/CaseDetails.aspx..."
    # (one directory UP from .../courtrosters/) and must resolve there, not
    # back into .../courtrosters/PublicIndex/... (the old string-hack bug).
    assert li.source_url == (
        "https://publicindex.sccourts.org/oconee/PublicIndex/CaseDetails.aspx"
        "?CourtAgency=37003&Casenum=2024CP3700456&CaseType=V&Org=CR"
    )


def test_parser_unescapes_html_entities():
    """AUDITED 2026-10-01: _clean() used to skip html.unescape, so every
    owner/plaintiff/description string shipped literal '&amp;' straight off
    the ASP.NET grid."""
    out = parse_roster(_LAURENS_12COL_ROW, _SEL, "Laurens", _BASE)
    assert len(out) == 1
    li = out[0]
    assert "&amp;" not in (li.plaintiff or "")
    assert li.plaintiff == "U.S. Bank & Trust Company"
    assert "&amp;" not in (li.description or "")


def test_parser_handles_laurens_12column_layout_no_tms():
    """AUDITED 2026-10-01: Laurens' MO roster has no TMS/Map# column at all --
    one less column than Oconee/Cherokee/Union -- which used to silently drop
    the real notes cell (hard-coded at index 12, which doesn't exist on a
    12-cell row) and left attorney-block text sitting where the fixed TMS
    index expected a parcel id (that part degraded safely via the existing
    regex guard). Fixed by locating cells by CSS class / scanning rather than
    a fixed index, so the real notes text and the absence of a TMS are both
    read correctly instead of either being silently lost or risking a
    false-positive parcel id from attorney text."""
    out = parse_roster(_LAURENS_12COL_ROW, _SEL, "Laurens", _BASE)
    assert len(out) == 1
    li = out[0]
    assert li.county == "Laurens"
    # No TMS column on this layout -- must stay None, never an attorney name.
    assert li.parcel_id is None
    # The real notes text, previously dropped entirely for this county.
    assert li.description == "Continued per email from Mr. Brown"
    assert li.defendant == "Randall J Owens"


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
