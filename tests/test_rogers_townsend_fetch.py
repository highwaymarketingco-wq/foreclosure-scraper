"""Rogers Townsend SC report: retry, honest outcome, and the Bid / DJ Demand columns.

Audit 2026-10-08: the gated VM run scraped 0 rows (previous run 32) while SC_Listings.pdf was
live at the same URL and parsed to 33 rows the same day. One failed or empty fetch used to come
back as a clean ZERO_RESULT (no retry, no reason, no carryover). The report's "$0.00" Bid cell
is a no-bid placeholder that was published as a $0 opening bid, and the DJ Demand flag was
dropped. Fixtures are invented (made-up streets, parcel ids and amounts).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from foreclosure_scraper.base_scraper import OUTCOME_ZERO
from foreclosure_scraper.scrapers.law_firms import rogers_townsend as rt

_HEADER = ["County", "Street Address", "City", "Tax Map No.", "Sale Date", "DJ Demand", "Bid"]
_ROWS = [
    _HEADER,
    ["Spartanburg", "100 Example Lane", "Testville", "1-11-11-111.00", "11/2/2026", "N", "$0.00"],
    [None, "200 Sample Road", "Testville", "2-22-22-222.00", "11/2/2026", "Y", "$12,345.67"],
    ["Oconee", "300 Fixture Drive", "Mocktown", "333-00-03-003", "11/3/2026", "N", ""],
]


class _FakePage:
    def __init__(self, rows):
        self._rows = rows

    def extract_tables(self):
        return [self._rows]


class _FakePdf:
    def __init__(self, rows):
        self.pages = [_FakePage(rows)]

    def close(self):
        pass


class _Resp:
    def __init__(self, status: int, content: bytes, ct: str):
        self.status_code = status
        self.content = content
        self.headers = {"content-type": ct}
        self.text = content.decode("latin-1")

    def raise_for_status(self):
        req = httpx.Request("GET", rt.SC_URL)
        raise httpx.HTTPStatusError("err", request=req,
                                    response=httpx.Response(self.status_code, request=req))


_PDF = _Resp(200, b"%PDF-1.3 fixture", "application/pdf")
_CHALLENGE = _Resp(200, b"<!DOCTYPE html><html>challenge</html>", "text/html")
_NC_404 = _Resp(404, b"<!doctype html>not found", "text/html")


def _patch(monkeypatch, sc_responses):
    """sc_responses: list of _Resp or Exception, consumed one per SC GET."""
    calls = {"sc": 0}

    class _Client:
        async def get(self, url):
            if url == rt.NC_URL:
                return _NC_404
            item = sc_responses[calls["sc"]]
            calls["sc"] += 1
            if isinstance(item, Exception):
                raise item
            return item

    @asynccontextmanager
    async def _client(**_kw):
        yield _Client()

    monkeypatch.setattr(rt, "client", _client)
    monkeypatch.setattr(rt, "SC_RETRY_DELAY_S", 0.0, raising=False)
    monkeypatch.setattr(rt.pdfplumber, "open", lambda _buf: _FakePdf(_ROWS))
    return calls


def test_transient_failure_is_retried(monkeypatch):
    calls = _patch(monkeypatch, [httpx.ConnectTimeout("connect timed out"), _PDF])
    out = list(asyncio.run(rt.RogersTownsend().fetch()))
    assert calls["sc"] == 2
    assert len(out) == 3


def test_challenge_page_then_pdf_is_retried(monkeypatch):
    _patch(monkeypatch, [_CHALLENGE, _PDF])
    out = list(asyncio.run(rt.RogersTownsend().fetch()))
    assert len(out) == 3


def test_persistent_failure_is_not_a_clean_zero(monkeypatch):
    _patch(monkeypatch, [_CHALLENGE, _CHALLENGE])
    s = rt.RogersTownsend()
    out = asyncio.run(s.safe_run())
    assert out == []
    assert s.last_outcome != OUTCOME_ZERO
    assert "non-PDF" in s.last_reason


def test_zero_bid_placeholder_and_dj_demand(monkeypatch):
    _patch(monkeypatch, [_PDF])
    out = list(asyncio.run(rt.RogersTownsend().fetch()))
    by_parcel = {li.parcel_id: li for li in out}
    assert by_parcel["1-11-11-111.00"].opening_bid is None          # "$0.00" placeholder
    assert by_parcel["2-22-22-222.00"].opening_bid == pytest.approx(12345.67)
    assert by_parcel["2-22-22-222.00"].county == "Spartanburg"      # carried down
    assert "DJ Demand: Y" in (by_parcel["2-22-22-222.00"].description or "")
    assert "DJ Demand: N" in (by_parcel["1-11-11-111.00"].description or "")


def test_expected_min_alarms_on_zero():
    assert rt.RogersTownsend.expected_min_count > 0
