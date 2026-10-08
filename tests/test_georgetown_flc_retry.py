"""Georgetown CivicEngage: one failed FLC page read is retried instead of losing the list.

10/8 VM run: the FLC page read failed once ("georgetown.flc_fail", empty message) and the
whole 55-row FLC list was lost while the tax-sale and MIE pages read fine moments later.
"""
from __future__ import annotations

import asyncio

import httpx

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.scrapers.counties_sc import georgetown_civicengage as mod

FLC_HTML = '<a href="/DocumentCenter/View/1/2026-FLC-LIST">2026 FLC List</a>'


class _Resp:
    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.text = text


class _Client:
    def __init__(self):
        self.flc_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, *a, **k):
        if url == mod.FLC_PAGE:
            self.flc_calls += 1
            if self.flc_calls == 1:
                raise httpx.ReadTimeout("")
            return _Resp(200, FLC_HTML)
        return _Resp(404)


def test_flc_page_read_is_retried_once(monkeypatch):
    cli = _Client()
    monkeypatch.setattr(mod, "client", lambda *a, **k: cli)

    async def fake_pdf(self, c, url):
        return b"%PDF-1.4"

    monkeypatch.setattr(mod.GeorgetownCivicEngage, "_get_pdf", fake_pdf)
    monkeypatch.setattr(mod, "_pdf_text", lambda data: "text")
    flc_row = Listing(source=mod.GeorgetownCivicEngage.slug, source_url="https://example.invalid/flc",
                      listing_type=ListingType.TAX_SALE, state="SC", county="Georgetown",
                      parcel_id="01-0001-001-00-00")
    monkeypatch.setattr(mod, "parse_flc", lambda text, url: [flc_row])

    rows = list(asyncio.run(mod.GeorgetownCivicEngage().fetch()))
    assert cli.flc_calls == 2
    assert [r.parcel_id for r in rows] == ["01-0001-001-00-00"]
