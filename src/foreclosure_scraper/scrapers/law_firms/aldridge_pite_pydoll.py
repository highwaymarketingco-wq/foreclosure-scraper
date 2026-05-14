"""Aldridge Pite — pydoll-based A/B variant.

Companion to scrapers/law_firms/aldridge_pite.py (Scrapling stealth).
Both target aldridgepite.com/.../foreclosure-listings-north-carolina/.
The differentiator is the disclaimer-modal click: Scrapling has been
producing 0 listings on this site (verified patch run #14 2026-05-14)
despite the disclaimer-button selector chain. Hypothesis: aldridgepite's
disclaimer-page uses some form of bot detection that flags Scrapling
even when the click event fires.

Pydoll drives Chrome via raw CDP with realistic mouse press/release
events (vs Scrapling's Playwright synthetic click). If that's the
difference, pydoll's flow should land us on the listings table.

Run side-by-side as `law_firms.aldridge_pite_pydoll`. Compare counts
in run_health.json:
  - Scrapling=0, pydoll>0 → migrate to pydoll
  - Both 0 → site genuinely empty or our parser is wrong
  - Scrapling>0, pydoll>0 → both work, no migration

Parser reused from aldridge_pite.py via _parse_listings import.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing
from .aldridge_pite import _parse_listings  # reuse the same parser

log = structlog.get_logger()

URLS = (
    ("https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-north-carolina/", "NC"),
)


async def _fetch_state_pydoll(url: str) -> str:
    """Drive the disclaimer-modal click via pydoll's CDP-native flow.
    Returns rendered listings HTML or empty string on failure."""
    try:
        from pydoll.browser import Chrome
        from pydoll.browser.options import ChromiumOptions
    except ImportError:
        log.warning("aldridge_pydoll.import_fail", hint="pip install pydoll-python")
        return ""

    options = ChromiumOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")

    html = ""
    try:
        async with Chrome(options=options) as browser:
            tab = await browser.start()
            await tab.go_to(url)
            # Let any disclaimer modal render
            await asyncio.sleep(3)
            # Click the I Agree button across multiple candidate selectors.
            # pydoll uses real CDP click events with mouse-down + mouse-up
            # timing instead of Playwright's synthetic dispatchEvent.
            agree_selectors = [
                'a:contains("I AGREE")',
                'a:contains("I Agree")',
                'button:contains("I AGREE")',
                'button:contains("Accept")',
                'a:contains("Accept")',
                'a.disclaimer-accept',
                'input[type="submit"][value*="Agree"]',
            ]
            for sel in agree_selectors:
                try:
                    el = await tab.query(sel)
                    if el:
                        await el.click()
                        await asyncio.sleep(3)  # let the post-click load settle
                        break
                except Exception:
                    continue
            # Give the post-disclaimer listings table time to render
            await asyncio.sleep(4)
            html = await tab.page_source
    except Exception as exc:
        log.warning("aldridge_pydoll.fetch_fail", url=url, error=str(exc)[:200])
        return ""
    return html or ""


class AldridgePitePydoll(BaseScraper):
    slug = "law_firms.aldridge_pite_pydoll"
    name = "Aldridge Pite (NC, pydoll A/B variant)"
    category = "law_firm"
    requires_apify = False
    requires_render = True
    expected_min_count = 0
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for url, state in URLS:
            html = await _fetch_state_pydoll(url)
            out.extend(_parse_listings(html, url, state, self.slug))
        log.info("aldridge_pydoll.done", count=len(out))
        return out
