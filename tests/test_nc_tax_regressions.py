"""Regression tests for the two NC county-tax sources that fell to 0 rows.

Both were flagged "REGRESSED (expected >= 1)" by the 2026-08-02 full run. Each
fixture is the live page/feed saved on the day of the fix.

polk_tax   — Kania posts "$TBD" until the upset-bid figure is set; the old row
             regex required digits after the "$" and matched nothing.
buncombe_tax — the Trumba event date is the BIDDING-BEGINS date (in the past for
             every open parcel), custom fields are keyed by "label" not "name",
             and redeemed parcels must be dropped.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from foreclosure_scraper.scrapers.counties_nc.buncombe_tax import (
    LOOKAHEAD_DAYS,
    LOOKBACK_DAYS,
    BuncombeTax,
)
from foreclosure_scraper.scrapers.counties_nc.polk_tax import PolkTaxAuction

FIXTURES = Path(__file__).parent / "fixtures"


# --- polk_tax ---------------------------------------------------------------

def _polk_rows(html: str) -> list:
    """Run the scraper's parse over fixture HTML without touching the network."""
    import asyncio

    class _Resp:
        status_code = 200
        text = html

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *a, **kw):
            return _Resp()

    import foreclosure_scraper.scrapers.counties_nc.polk_tax as mod

    original = mod.client
    mod.client = lambda **kw: _Client()
    try:
        return list(asyncio.run(PolkTaxAuction().fetch()))
    finally:
        mod.client = original


def test_polk_parses_tbd_opening_bid():
    """The live page carries one parcel priced '$TBD'. It must still be emitted."""
    html = (FIXTURES / "polk_tax_upcoming_auction.html").read_text()
    rows = _polk_rows(html)
    assert rows, "TBD-priced auction row was dropped (the 0-row regression)"
    row = rows[0]
    assert row.parcel_id == "P65-38"
    assert row.opening_bid is None      # '$TBD' is not a price
    assert row.sale_date is not None    # header date still parses
    assert row.county == "Polk"
    assert row.state == "NC"


def test_polk_still_parses_a_numeric_bid():
    """A priced row keeps working — the TBD branch must not swallow amounts."""
    html = "<html><body>PARCEL OPENING BID P12-34 &nbsp; $1,234.56</body></html>"
    rows = _polk_rows(html)
    assert len(rows) == 1
    assert rows[0].parcel_id == "P12-34"
    assert rows[0].opening_bid == pytest.approx(1234.56)


# --- buncombe_tax -----------------------------------------------------------

def _buncombe_rows(events: list[dict]) -> list:
    import asyncio

    class _Resp:
        status_code = 200

        def __init__(self, payload):
            self.text = json.dumps(payload)

    class _Client:
        def __init__(self, payload):
            self._payload = payload
            self.params = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, **kw):
            self.params = params
            captured.append(params)
            return _Resp(self._payload)

    import foreclosure_scraper.scrapers.counties_nc.buncombe_tax as mod

    captured: list = []
    original = mod.client
    mod.client = lambda **kw: _Client(events)
    try:
        rows = list(asyncio.run(BuncombeTax().fetch()))
    finally:
        mod.client = original
    return rows, captured[0]


def test_buncombe_window_looks_backwards():
    """The regression: querying from today matched 0 events because every open
    parcel's bidding-begins date is in the past."""
    _, params = _buncombe_rows([])
    start = datetime.strptime(params["startdate"], "%Y%m%d")
    end = datetime.strptime(params["enddate"], "%Y%m%d")
    today = datetime.utcnow()
    assert start < today - timedelta(days=365), "window must reach back past open parcels"
    assert (today - start).days == pytest.approx(LOOKBACK_DAYS, abs=2)
    assert (end - today).days == pytest.approx(LOOKAHEAD_DAYS, abs=2)


def test_buncombe_parses_label_keyed_custom_fields_and_drops_redeemed():
    events = json.loads((FIXTURES / "buncombe_trumba_events.json").read_text())
    rows, _ = _buncombe_rows(events)

    redeemed = [
        e for e in events
        if any((cf.get("label") == "Redeemed"
                and str(cf.get("value", "")).lower().startswith("y"))
               for cf in e.get("customFields") or [])
    ]
    assert redeemed, "fixture should contain redeemed events to prove they're dropped"
    assert len(rows) == len(events) - len(redeemed)

    # Custom fields are keyed by "label"; the old code read "name" and got None.
    for row in rows:
        assert row.case_number, "case number must come off the label-keyed field"
        assert row.opening_bid and row.opening_bid > 0
        assert row.parcel_id and row.parcel_id.isdigit(), "GIS PIN must be parsed"
        assert row.county == "Buncombe"
        assert row.state == "NC"


def test_buncombe_past_bidding_start_is_not_stamped_as_sale_date():
    """Recovering the rows is worthless if the board then drops them.

    startDateTime is bidding-BEGINS, not an auction date, so every open parcel
    carries a past date. Stamping it as sale_date made main._active_only discard
    33 of 33 live rows — the fetch read 0 -> 33 while the board stayed at 0. A
    past start must be withheld (and preserved in raw) so the row can travel the
    dateless lane; a future start is a real scheduled event and keeps its date.
    """
    from foreclosure_scraper import main as m

    events = json.loads((FIXTURES / "buncombe_trumba_events.json").read_text())
    rows, _ = _buncombe_rows(events)
    assert rows, "fixture must yield live rows"

    # Fixture starts are all historic (2022-...), so nothing may carry a sale_date.
    assert all(r.sale_date is None for r in rows)
    for r in rows:
        blob = r.raw["buncombe_tax"]
        assert blob["sale_date_withheld"] is True
        assert blob["bidding_begins_iso"], "the real date must survive in raw"

    # Withholding alone is not enough — the source also needs the dateless
    # whitelist entry. Both halves are now in place, so assert against the REAL
    # config (rows survive), then remove the entry to prove it is load-bearing.
    assert "counties_nc.buncombe_tax" in m.DATELESS_OK_SOURCES
    assert all(m._active_only(r, 120) for r in rows)

    stripped = set(m.DATELESS_OK_SOURCES) - {"counties_nc.buncombe_tax"}
    original, m.DATELESS_OK_SOURCES = m.DATELESS_OK_SOURCES, stripped
    try:
        assert not any(m._active_only(r, 120) for r in rows), (
            "without the dateless whitelist entry every recovered row is dropped"
        )
    finally:
        m.DATELESS_OK_SOURCES = original

    # A genuinely future start still gets dated.
    future = json.loads(json.dumps(events[0]))
    future["startDateTime"] = (datetime.utcnow() + timedelta(days=30)).isoformat()
    for cf in future.get("customFields") or []:
        if cf.get("label") == "Redeemed":
            cf["value"] = "No"
    dated, _ = _buncombe_rows([future])
    assert dated and dated[0].sale_date is not None
    assert dated[0].raw["buncombe_tax"]["sale_date_withheld"] is False
