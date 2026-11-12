"""Bell Carrington Price & Gregg — public Google Sheets CSV foreclosure docket.

Live-verified 2026-10-01: the published CSV covers AL/GA/LA/MS/NC/SC/TN in one
sheet (section-header rows like ",GA,,,,,,," mark states with zero current
listings) and filters to NC/SC. The "Notes" column sometimes carries the real
NC court case number (e.g. "26SP000141-280") rather than a free-text note —
the scraper used to drop it into description only and never promoted it to
case_number, so every row lost its docket number even when the source had it.

Live-verified 2026-10-04: when "Bid" is the status word "Postponed" (instead
of a dollar amount or "TBA"), Notes carries the NEW sale date/time (e.g.
"11/12/2026 at 11:30 AM"), not a case number -- confirmed against the real
live CSV's own current Mecklenburg row. The original Sale Date column still
shows the OLD, superseded date. Added auction_status="postponed" plus
promoting the Notes date to the effective sale_date.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.law_firms import bell_carrington as bc

# A trimmed, real-shaped sample mirroring the live CSV: leading blank row,
# header row, blank separator, AL section with data, an empty-section state
# header (GA), then NC/SC rows — including a real case-number Notes value, a
# plain status Notes value, and a blank Notes value.
_SAMPLE_CSV = (
    " ,,,,,,,\n"
    " Sale Date,State,Property,City,Zip,County,Bid,Notes\n"
    ",,,,,,,\n"
    "10/2/2026,AL,4224 Fieldstone Drive,Birmingham,35215,Jefferson,TBA,\n"
    ",,,,,,,\n"
    ",GA,,,,,,\n"
    ",,,,,,,\n"
    "10/6/2026,NC,875 Marys Grove Road,Cherryville,28021,Gaston,TBA,26SP000375-350\n"
    "10/8/2026,NC,6317 Woodland Commons Drive,Charlotte,28269,Mecklenburg,Postponed,11/12/2026 at 11:30 AM\n"
    "10/5/2026,SC,123 Robinhood Lane,Gaffney,29340,Cherokee,\"$153,033.13\",Deficiency Demanded\n"
    "10/5/2026,SC,200 Murray Drive,Cheraw,29520,Chesterfield,TBA,\n"
)


def test_nc_notes_case_number_promoted(monkeypatch):
    async def fake_get_text(url, timeout=30.0):
        return _SAMPLE_CSV

    monkeypatch.setattr(bc, "get_text", fake_get_text)
    out = list(asyncio.run(bc.BellCarrington().fetch()))

    nc = [li for li in out if li.state == "NC"]
    assert len(nc) == 2
    by_addr = {li.street_address: li for li in nc}
    assert by_addr["875 Marys Grove Road"].case_number == "26SP000375-350"
    assert by_addr["875 Marys Grove Road"].description is None


def test_postponed_bid_promotes_notes_date_and_status(monkeypatch):
    """A "Postponed" Bid value means Notes carries the new sale date/time,
    not a case number -- the original Sale Date column is stale."""
    async def fake_get_text(url, timeout=30.0):
        return _SAMPLE_CSV

    monkeypatch.setattr(bc, "get_text", fake_get_text)
    out = list(asyncio.run(bc.BellCarrington().fetch()))

    row = next(li for li in out if li.street_address == "6317 Woodland Commons Drive")
    assert row.auction_status == "postponed"
    assert row.case_number is None
    assert row.opening_bid is None
    # The effective sale_date is the NEW date from Notes, not the stale
    # original "10/8/2026" from the Sale Date column.
    assert row.sale_date is not None
    assert row.sale_date.year == 2026 and row.sale_date.month == 11 and row.sale_date.day == 12


def test_sc_notes_free_text_not_mistaken_for_case_number(monkeypatch):
    async def fake_get_text(url, timeout=30.0):
        return _SAMPLE_CSV

    monkeypatch.setattr(bc, "get_text", fake_get_text)
    out = list(asyncio.run(bc.BellCarrington().fetch()))

    sc = {li.street_address: li for li in out if li.state == "SC"}
    assert sc["123 Robinhood Lane"].case_number is None
    assert sc["123 Robinhood Lane"].description == "Deficiency Demanded"
    assert sc["123 Robinhood Lane"].opening_bid == 153033.13
    assert sc["200 Murray Drive"].case_number is None
    assert sc["200 Murray Drive"].description is None


def test_non_footprint_states_excluded(monkeypatch):
    async def fake_get_text(url, timeout=30.0):
        return _SAMPLE_CSV

    monkeypatch.setattr(bc, "get_text", fake_get_text)
    out = list(asyncio.run(bc.BellCarrington().fetch()))
    assert all(li.state in ("NC", "SC") for li in out)
    assert len(out) == 4


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "law_firms.bell_carrington" in {s.slug for s in all_scrapers()}
