"""foreclosure_dot_com: the first block status ends the run instead of asking every other URL.

Source-completeness audit 2026-10-08: the host answers its "VPN or proxy" 403 page to the whole
site (homepage included), and the VM's gated run spent 7.5 minutes asking all 37 URLs, each
retried inside get_text_impersonate. These tests fail on that code. Invented addresses.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from foreclosure_scraper.scrapers.national import foreclosure_dot_com as mod

TARGET = "foreclosure_scraper.scrapers.national.foreclosure_dot_com.get_text_impersonate"

SEARCH_NC = (
    "<html><head><title>1 Foreclosure Listings in North Carolina</title></head><body>"
    + "<!--" + "x" * 5200 + "-->"
    + '<div id="clone_1"><a href="/address/Testa-Placeholder-Rd-Shelby-NC-28150/123456_lid">'
      '<img alt="View this home at Testa Placeholder Rd, Shelby, NC 28150" '
      'src="//img.example/listingphoto/1.jpg"></a> $123,000 Single-Family</div>'
    "</body></html>"
)


def test_the_first_block_stops_the_run():
    calls: list[str] = []

    async def blocked(url, **kw):
        calls.append(url)
        raise RuntimeError("impersonate got 403 for " + url)

    with patch(TARGET, side_effect=blocked):
        out = asyncio.run(mod.ForeclosureDotCom().fetch())
    assert out == []
    assert len(calls) == 1


def test_rows_read_before_the_block_are_kept():
    calls: list[str] = []

    async def nc_then_blocked(url, **kw):
        calls.append(url)
        if "North%20Carolina" in url:
            return SEARCH_NC
        raise RuntimeError("impersonate got 403 for " + url)

    with patch(TARGET, side_effect=nc_then_blocked):
        out = asyncio.run(mod.ForeclosureDotCom().fetch())
    assert [li.case_number for li in out] == ["fc-123456"]
    assert len(calls) == 2


def test_a_non_block_error_does_not_stop_the_run():
    calls: list[str] = []

    async def flaky(url, **kw):
        calls.append(url)
        raise RuntimeError("timed out")

    with patch(TARGET, side_effect=flaky):
        asyncio.run(mod.ForeclosureDotCom().fetch())
    assert len(calls) == len(mod.SEARCH_URLS) + len(mod.CITY_URLS)
