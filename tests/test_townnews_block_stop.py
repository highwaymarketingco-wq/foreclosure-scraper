"""TownNews legal-notice scrapers stop at the first 403/429 instead of asking the next feed URL.

Source-completeness audit 2026-10-08: journal_scene, post_and_courier, index_journal and
carolina_coast all ended BLOCKED on the VM's gated run (HTTP 429), and one ordinary request
from the Mac drew 429 "Too Many Requests" from postandcourier.com, carolinacoastonline.com and
thedigitalcourier.com. Each feed URL after the first 429 was asked anyway (and retried inside
get_text). These tests fail on that code. Invented notice text.
"""
from __future__ import annotations

import asyncio
import importlib

import httpx
import pytest

MODULES = {
    "journal_scene": "JournalSceneForeclosures",
    "post_and_courier": "PostAndCourierForeclosures",
    "index_journal": "IndexJournalForeclosures",
    "carolina_coast": "CarolinaCoastForeclosures",
    "aiken_standard": "AikenStandardForeclosures",
}

FEED = (
    "<rss><channel><item><title>NOTICE OF SALE C/A NO: 2026-CP-02-09999</title>"
    "<link>https://example.test/notice-1</link>"
    "<description>Master in Equity sale. Testa Lender, LLC, Plaintiff, vs. Morrow Example, "
    "Defendant. 12 Placeholder Road, Nowhere, SC 29801</description>"
    "<pubDate>Thu, 01 Oct 2026 08:00:00 -0400</pubDate></item></channel></rss>"
)


FEED_NC = (
    "<rss><channel><item><title>NOTICE OF FORECLOSURE SALE 26 SP 999</title>"
    "<link>https://example.test/notice-1</link>"
    "<description>NORTH CAROLINA, CARTERET COUNTY. Substitute Trustee will sell 12 Placeholder "
    "Road, Beaufort, NC 28516 under the deed of trust.</description>"
    "<pubDate>Thu, 01 Oct 2026 08:00:00 -0400</pubDate></item></channel></rss>"
)


def _err(url: str, code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", url)
    return httpx.HTTPStatusError(f"HTTP {code}", request=req, response=httpx.Response(code, request=req))


@pytest.mark.parametrize("name", sorted(MODULES))
def test_the_first_429_stops_the_feed_loop(monkeypatch, name):
    mod = importlib.import_module(f"foreclosure_scraper.scrapers.newspapers.{name}")
    calls: list[str] = []

    async def fake_get_text(url, **kw):
        calls.append(url)
        raise _err(url, 429)

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    out = asyncio.run(getattr(mod, MODULES[name])().fetch())
    assert list(out) == []
    assert len(calls) == 1


@pytest.mark.parametrize("name", sorted(MODULES))
def test_rows_from_feeds_before_the_429_are_kept(monkeypatch, name):
    mod = importlib.import_module(f"foreclosure_scraper.scrapers.newspapers.{name}")
    calls: list[str] = []

    async def fake_get_text(url, **kw):
        calls.append(url)
        if len(calls) == 1:
            return FEED_NC if name == "carolina_coast" else FEED
        raise _err(url, 429)

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    out = list(asyncio.run(getattr(mod, MODULES[name])().fetch()))
    assert len(calls) == 2
    assert [li.source_url for li in out] == ["https://example.test/notice-1"]


@pytest.mark.parametrize("name", sorted(MODULES))
def test_a_404_on_one_feed_still_moves_on(monkeypatch, name):
    mod = importlib.import_module(f"foreclosure_scraper.scrapers.newspapers.{name}")
    calls: list[str] = []

    async def fake_get_text(url, **kw):
        calls.append(url)
        raise _err(url, 404)

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    asyncio.run(getattr(mod, MODULES[name])().fetch())
    assert len(calls) == len(mod.FEED_URLS)
