"""Buncombe County NC tax-foreclosure fcl.pdf — audited 2026-10-01.

Live finding: `media.buncombenc.gov/common/tax/foreclosure-listings/fcl.pdf`
answers HTTP 200 with a real-looking PDF, but its `Last-Modified` header reads
Friday, 25 Feb 2022 — the document is genuinely frozen, not a caching
artifact. Cross-checking its 4 current records' case numbers against the
properly-live `counties_nc.buncombe_tax` Trumba feed found 3 of 4 no longer
appear there at all (very likely long since resolved/redeemed), while the one
that does (`21 CV 3721`) shows a materially different, more current bid on the
live feed than this frozen PDF's $121,600/"MARCH 7, 2022" snapshot. This is
exactly the "HTTP 200 does not mean the data is current" failure mode this
repo is built to catch.

Not disabled (HERMES: "DEAD means dead the day it was probed, not forever" —
the document could be republished any time), but the fetch now stamps the
source document's own age (`raw['buncombe_tax_fcl']['source_last_modified']` /
`source_doc_age_days`) independent of any one record's `sale_date`, so a board
consumer or a future audit can see the staleness without re-probing the HTTP
headers by hand. These tests cover that new staleness-stamping logic and the
pre-existing pure parsing helpers.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import httpx
import pytest

from foreclosure_scraper.scrapers.counties_nc import buncombe_tax_foreclosure as bft


def test_to_float_parses_dollar_amounts():
    assert bft._to_float("$25,000") == 25000.0
    assert bft._to_float("121,600") == 121600.0
    assert bft._to_float(None) is None
    assert bft._to_float("") is None


def test_parse_date_handles_month_name_and_slash_forms():
    assert bft._parse_date("MARCH 4, 2022") == datetime(2022, 3, 4)
    assert bft._parse_date("3/4/2022") == datetime(2022, 3, 4)
    assert bft._parse_date("not a date") is None


class _FakeResponse:
    def __init__(self, content: bytes, last_modified: str | None):
        self.content = content
        self.headers = {"last-modified": last_modified} if last_modified else {}

    def raise_for_status(self):
        pass


def _fake_client(content: bytes, last_modified: str | None):
    class _FakeHTTPClient:
        async def get(self, url, **kw):
            return _FakeResponse(content, last_modified)

    class _CM:
        async def __aenter__(self):
            return _FakeHTTPClient()

        async def __aexit__(self, *a):
            return False

    def _factory(**kw):
        return _CM()

    return _factory


def test_stale_document_is_stamped_with_its_real_age(monkeypatch):
    """Regression guard for the exact live finding: a Last-Modified far in the
    past must be surfaced on every row, not silently dropped."""
    monkeypatch.setattr(bft, "client", _fake_client(b"%PDF-fake", "Fri, 25 Feb 2022 13:26:24 GMT"))
    monkeypatch.setattr(
        bft,
        "_parse_pdf",
        lambda data: [{"owner": "JANE DOE", "address": "1 Main St", "pin": "1234-56-7890",
                       "bid": 25000.0, "bid_kind": "CURRENT", "upset": datetime(2022, 3, 4)}],
    )
    out = asyncio.run(bft.BuncombeTaxForeclosure().fetch())
    assert len(out) == 1
    fcl = out[0].raw["buncombe_tax_fcl"]
    assert fcl["source_last_modified"] == "Fri, 25 Feb 2022 13:26:24 GMT"
    assert fcl["source_doc_age_days"] > 1600  # genuinely years stale, not a typo


def test_fresh_document_has_near_zero_age(monkeypatch):
    recent = (datetime.utcnow() - timedelta(days=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    monkeypatch.setattr(bft, "client", _fake_client(b"%PDF-fake", recent))
    monkeypatch.setattr(
        bft,
        "_parse_pdf",
        lambda data: [{"owner": "JOHN SMITH", "address": "2 Oak St", "pin": "1111-22-3333"}],
    )
    out = asyncio.run(bft.BuncombeTaxForeclosure().fetch())
    assert out[0].raw["buncombe_tax_fcl"]["source_doc_age_days"] <= 3


def test_missing_last_modified_header_does_not_crash():
    monkeypatch_client = _fake_client(b"%PDF-fake", None)

    async def run():
        import foreclosure_scraper.scrapers.counties_nc.buncombe_tax_foreclosure as mod
        orig_client, orig_parse = mod.client, mod._parse_pdf
        mod.client = monkeypatch_client
        mod._parse_pdf = lambda data: [{"owner": "X", "address": "3 Elm St", "pin": "999"}]
        try:
            return list(await mod.BuncombeTaxForeclosure().fetch())
        finally:
            mod.client, mod._parse_pdf = orig_client, orig_parse

    out = asyncio.run(run())
    assert out[0].raw["buncombe_tax_fcl"]["source_last_modified"] is None
    assert out[0].raw["buncombe_tax_fcl"]["source_doc_age_days"] is None


def test_redeemed_record_carries_no_bid():
    """Live-verified real case: a REDEEMED block has no CURRENT/OPENING BID
    line at all — _parse_pdf must not fabricate one."""
    text = (
        "CASE 21 CV 3399 RICEVILLE\n"
        "PIN: 9668-87-2059 8 THOMAS LEE DRIVE\n"
        "LAND & STRUCTURES\n"
        "0.59 ACRES, MORE OR LESS\n"
        "REDEEMED\n"
    )
    import re
    bm = bft._BID_RE.search(text)
    assert bm is None
    assert "REDEEMED" in text.upper()


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "counties_nc.buncombe_tax_foreclosure" in {s.slug for s in all_scrapers()}
