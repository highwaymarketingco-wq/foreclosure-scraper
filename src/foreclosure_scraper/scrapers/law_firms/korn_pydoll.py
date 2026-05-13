"""Korn Law Firm — pydoll-based variant for A/B comparison.

This scraper is a pydoll-driven alternative to scrapers/law_firms/korn.py
(which uses Scrapling stealth). Both target the same site
(kornlawfirm.com/foreclosure-sales) with the same parser; the only
difference is the browser-automation library underneath.

Run side-by-side in production so we can compare bypass success:
  - law_firms.korn         → Scrapling/patchright (existing)
  - law_firms.korn_pydoll  → pydoll/CDP (this file)

If pydoll consistently produces listings where Scrapling produces 0,
we'll migrate the other 3 RENDER-REQUIRED scrapers (aldridge_pite,
mcmichael_taylor_gray, rogers_townsend) to pydoll too. If it produces
the same 0, we have a Korn-specific problem (e.g., the site genuinely
has no SC listings right now, or the parser is wrong).
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing
from .korn import _parse_html  # reuse the same parser

log = structlog.get_logger()

URLS = (
    "https://www.kornlawfirm.com/foreclosure-sales/",
    "https://www.kornlawfirm.com/sales/",
)


async def _fetch_via_pydoll(url: str) -> str:
    """Drive the Korn entry-splash + listings via pydoll.

    pydoll runs Chrome via raw CDP (no Selenium/Playwright detection
    surface). Realistic mouse + keyboard simulation by default. Returns
    the rendered HTML or empty string on failure.
    """
    try:
        from pydoll.browser import Chrome
        from pydoll.browser.options import ChromiumOptions
    except ImportError:
        log.warning("korn_pydoll.import_fail", hint="pip install pydoll-python")
        return ""

    options = ChromiumOptions()
    # Headless mode — required for CI, optional locally
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    # Avoid detection on /robots.txt-style automation flags
    options.add_argument("--disable-blink-features=AutomationControlled")

    html = ""
    try:
        async with Chrome(options=options) as browser:
            tab = await browser.start()
            await tab.go_to(url)
            # Give the splash + AJAX time to settle
            await asyncio.sleep(3)
            # Try to click any "Enter" splash if present
            for sel in (
                'a:contains("Click here to enter")',
                'a:contains("Enter")',
                'button:contains("Enter")',
                'a.enter-button',
            ):
                try:
                    el = await tab.query(sel)
                    if el:
                        await el.click()
                        await asyncio.sleep(2)
                        break
                except Exception:
                    continue
            html = await tab.page_source
    except Exception as exc:
        log.warning("korn_pydoll.fetch_fail", url=url, error=str(exc)[:200])
        return ""
    return html or ""


class KornPydoll(BaseScraper):
    slug = "law_firms.korn_pydoll"
    name = "Korn Law Firm (SC, pydoll A/B variant)"
    category = "law_firm"
    requires_apify = False
    requires_render = True
    expected_min_count = 0
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for url in URLS:
            html = await _fetch_via_pydoll(url)
            if not html:
                continue
            for li in _parse_html(html, url, self.slug):
                key = (li.street_address or "").upper() + "|" + (li.county or "")
                if key.strip("|") in seen:
                    continue
                seen.add(key.strip("|"))
                out.append(li)
            if out:
                break  # First successful URL is enough
        log.info("korn_pydoll.done", count=len(out))
        return out
