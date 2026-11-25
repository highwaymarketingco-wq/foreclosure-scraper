"""SC Department of Revenue Tax Lien Registry scraper.

NEW SOURCE discovered 2026-11-25 by Hermes independent verification.

URL: https://mydorway.dor.sc.gov/?link=LienRegistry
Status: LIVE, FREE, NO CAPTCHA, NO LOGIN
Data: SC state tax liens filed since Nov 1, 2019 (~14K+ rows estimated)

Search modes:
1. Lien ID (direct lookup)
2. Individual name (first + last)
3. Business name

Filters:
- Date range (from/to)
- Status: Active, Satisfied, or both

This is NOT a wall to break - it's a genuinely free, open public search.
Perfect example of what we want: government data with zero barriers.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper
from ...listing import Listing
from ...http_client import get_text

log = structlog.get_logger()

_BASE_URL = "https://mydorway.dor.sc.gov"
_SEARCH_URL = f"{_BASE_URL}/?link=LienRegistry"


class ScDorTaxLienScraper(BaseScraper):
    """SC DOR Tax Lien Registry - free statewide search."""

    slug = "counties_sc.sc_dor_tax_lien"
    name = "SC DOR Tax Lien Registry"
    category = "tax_lien"
    timeout_s = 180.0

    async def fetch(self) -> list[Listing]:
        """Fetch recent tax liens (last 90 days by default)."""
        results: list[Listing] = []

        # Date range: last 90 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)

        log.info(
            "sc_dor_lien.searching",
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
        )

        try:
            # Initial GET to get form tokens
            html = await get_text(_SEARCH_URL, timeout=30.0)
            soup = BeautifulSoup(html, "html.parser")

            # Extract ASP.NET form tokens (ViewState, EventValidation, etc.)
            viewstate = ""
            viewstate_generator = ""
            event_validation = ""

            for inp in soup.find_all("input", type="hidden"):
                name = inp.get("name", "")
                value = inp.get("value", "")

                if name == "__VIEWSTATE":
                    viewstate = value
                elif name == "__VIEWSTATEGENERATOR":
                    viewstate_generator = value
                elif name == "__EVENTVALIDATION":
                    event_validation = value

            if not viewstate:
                log.warning("sc_dor_lien.no_viewstate")
                return results

            # TODO: Figure out the actual form submission
            # The site uses ASP.NET postback with complex JavaScript
            # For now, return empty with note that it needs browser automation

            log.info(
                "sc_dor_lien.needs_browser",
                note="ASP.NET form with JavaScript - needs Playwright implementation",
            )

        except Exception as exc:
            log.warning("sc_dor_lien.fetch_failed", error=str(exc)[:200])

        return results


# ---------------------------------------------------------------------------
# Playwright version (use this when httpx version above doesn't work)
# ---------------------------------------------------------------------------


async def fetch_via_browser() -> list[Listing]:
    """Browser-based version for ASP.NET complexity."""
    results: list[Listing] = []

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.error("sc_dor_lien.no_playwright")
        return results

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(_SEARCH_URL, timeout=30000, wait_until="domcontentloaded")

            # Wait for search form
            await page.wait_for_selector("input, select, form", timeout=10000)

            # Set date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=90)

            # Find and fill date fields (need to inspect actual field IDs/names)
            # TODO: Inspect page and fill proper selectors

            # Click search button
            # TODO: Find actual search button selector

            # Wait for results
            await page.wait_for_load_state("networkidle", timeout=30000)

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Parse results table
            # TODO: Find actual results table structure and parse

            log.info("sc_dor_lien.results", count=len(results))

        except Exception as exc:
            log.warning("sc_dor_lien.browser_failed", error=str(exc)[:200])
        finally:
            await browser.close()

    return results
