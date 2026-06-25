"""Coastal SC Master-in-Equity sale-roster scraper (publicindex + SCDOT geo).

Added 2026-06-24 for the COASTAL track. Feeds the previously-empty oceanfront /
downtown-Charleston gate (main._check_oceanfront) by scraping the coastal SC
counties' Master-in-Equity foreclosure-SALE rosters and resolving each parcel
TMS/PIN to lat/lng via SCDOT at scrape time, so the near-beach ones can pass the
ingest-time scope gate (which needs coordinates, not just an address).
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.scrapers.counties_sc.sc_coastal_rosters import (
    COASTAL_COUNTIES,
    COUNTY_SALE_CODES,
    SCCoastalRosters,
    _PARCEL_CELL_RE,
    _tms_candidates,
    parse_sale_roster,
)

_SEL = "https://publicindex.sccourts.org/horry/courtrosters/RosterSelection.aspx"

# Horry MO layout (13 cols): "Master/Sale before Master", TMS at the 10th cell.
_HORRY_ROW = """<table><tr class="standardRow">
<td>1</td><td>06/01/2026</td><td>10:00 AM</td><td></td><td>Master/Sale before Master</td>
<td>Bank-PLT</td><td>04/01/2026</td>
<td><a href="CaseDetails.aspx?CaseID=1">2025CP2609320</a><br/>Bank vs Sherry Battle-Edmonds, defendant</td>
<td>Foreclosure 420</td><td>1860801332</td><td>Atty</td><td></td><td>Judgment $250,000.00</td></tr></table>"""

# Beaufort SALE layout (9 cols): R-prefixed PIN at the 8th cell, $ in last cell.
_BEAUFORT_ROW = """<table><tr class="altRow">
<td>1</td>
<td>2025CP0702550 Colleton River Co , plaintiff, et al vs Lawrence Crowley, defendant</td>
<td>Barry L. Johnson  (843) 555-1212</td><td></td><td>10/16/2025</td>
<td>Foreclosure 420</td><td>Sale; Deficiency Waived</td>
<td>R60002500000480000</td><td>Judgment $436,513.24. Deficiency Waived</td></tr></table>"""

# A row that is NOT a foreclosure (must be skipped).
_NON_FC_ROW = """<table><tr class="standardRow">
<td>1</td><td>06/01/2026</td><td>9:00 AM</td><td></td><td>Surplus Petition</td>
<td>Someone</td><td>04/01/2026</td><td><a>2025CP0700001</a></td>
<td>Debt Collection 110</td><td>1234567890</td></tr></table>"""

# A foreclosure row with NO parcel identifier (Beaufort MO hearing docket style)
# — must be skipped because it can't be geo-resolved for the near-beach gate.
_FC_NO_PARCEL_ROW = """<table><tr class="standardRow">
<td>1</td><td>07/17/2026</td><td>9:30 AM</td><td></td><td>Surplus Petition</td>
<td>Asset Recovery Inc-OTH</td><td>04/15/2026</td>
<td>2021CP0701402 Bank , plaintiff vs James Barkley, defendant</td>
<td>Foreclosure 420</td><td>Genevieve Speese Johnson  (757) 999-2099</td>
<td>James Calvin Barkley</td><td></td></tr></table>"""


def test_parses_horry_mo_layout():
    out = parse_sale_roster(_HORRY_ROW, _SEL, "Horry")
    assert len(out) == 1
    li = out[0]
    assert li.county == "Horry"
    assert li.state == "SC"
    assert li.case_number == "2025CP2609320"
    assert li.parcel_id == "1860801332"
    assert li.foreclosure_process == "judicial"
    assert li.opening_bid == 250000.0
    assert li.source == "counties_sc.sc_coastal_rosters"


def test_parses_beaufort_sale_layout():
    out = parse_sale_roster(_BEAUFORT_ROW, _SEL, "Beaufort")
    assert len(out) == 1
    li = out[0]
    assert li.county == "Beaufort"
    assert li.case_number == "2025CP0702550"
    assert li.parcel_id == "R60002500000480000"
    assert li.opening_bid == 436513.24


def test_skips_non_foreclosure_rows():
    assert parse_sale_roster(_NON_FC_ROW, _SEL, "Beaufort") == []


def test_skips_foreclosure_rows_without_parcel():
    # No parcel -> can't resolve to lat/lng -> can't pass the near-beach gate.
    assert parse_sale_roster(_FC_NO_PARCEL_ROW, _SEL, "Beaufort") == []


def test_parcel_cell_regex_accepts_real_formats():
    assert _PARCEL_CELL_RE.match("1860801332")          # Horry bare TMS
    assert _PARCEL_CELL_RE.match("369-110-100-30")      # Horry dashed
    assert _PARCEL_CELL_RE.match("R60002500000480000")  # Beaufort R-PIN
    assert _PARCEL_CELL_RE.match("R600 025 000 0048 00")
    assert not _PARCEL_CELL_RE.match("Surplus Petition")
    assert not _PARCEL_CELL_RE.match("9:30 AM")
    assert not _PARCEL_CELL_RE.match("5")


def test_tms_candidates_numeric_and_grouped():
    # dashed numeric -> add dash-free form
    assert "36911010030" in _tms_candidates("369-110-100-30")
    # R-PIN -> add the spaced 3-3-3-4-4 grouped form
    c = _tms_candidates("R60002500000480000")
    assert "R600 025 000 0048 0000" in c
    # truncated trailing group ("...0185 00") -> padded "...0185 0000"
    c2 = _tms_candidates("R100 024 000 0185 00")
    assert "R100 024 000 0185 0000" in c2


def test_charleston_excluded():
    # Charleston's publicindex courtrosters app exposes NO Master roster, so it
    # must not be crawled here (downtown-Charleston leads come from elsewhere).
    assert "charleston" not in COASTAL_COUNTIES
    assert "charleston" not in COUNTY_SALE_CODES


def test_county_codes_cover_every_county():
    assert set(COUNTY_SALE_CODES) == set(COASTAL_COUNTIES)


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    slugs = {s.slug for s in all_scrapers()}
    assert "counties_sc.sc_coastal_rosters" in slugs


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live SC publicindex + SCDOT — slow; set RUN_NETWORK_TESTS=1",
)
def test_live_yields_geocoded_coastal_rows():
    out = list(asyncio.run(SCCoastalRosters().fetch()))
    assert out, "expected at least one coastal foreclosure row"
    geocoded = [li for li in out if li.latitude is not None and li.longitude is not None]
    # The whole point: rows must carry coordinates so the near-beach gate works.
    assert geocoded, "expected coordinates resolved via SCDOT"
    for li in out:
        assert li.state == "SC"
        assert li.county in COASTAL_COUNTIES.values()
