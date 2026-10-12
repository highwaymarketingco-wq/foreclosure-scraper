"""NC Unclaimed Property — nccash.gov Cloudflare Turnstile.

unclaimed.nccash.gov hosts NC's unclaimed property database behind a
Cloudflare Turnstile challenge. The Angular SPA calls POST /SWS/properties
with a Turnstile token.

Strategy: Use pydoll (Cloudflare Turnstile bypass) to render the page,
solve Turnstile automatically, then execute search queries through the
browser. The Angular app makes XHR calls to /SWS/properties — we intercept
those responses.

If pydoll is unavailable or fails, fall back to Playwright with the
enrichment_waf_oss solver.
"""
from __future__ import annotations

import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_URL = "https://unclaimed.nccash.gov/"
_API = "https://unclaimed.nccash.gov/SWS/properties"

# Common NC surnames for unclaimed property search
_SEARCH_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones",
    "Davis", "Miller", "Wilson", "Moore", "Taylor",
]


class NcUnclaimedScraper(BaseScraper):
    """NC Unclaimed Property — Turnstile via pydoll/Playwright."""

    slug = "national.nc_unclaimed"
    name = "NC Unclaimed Property"
    category = "unclaimed"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            from ...wall_bypass import fetch_with_pydoll
            html = await fetch_with_pydoll(_URL, timeout_s=120)
            if html and len(html) > 1500:
                results = self._search_via_browser(html)
                if results:
                    return results
        except Exception as exc:
            log.warning("nc_unclaimed.pydoll_failed", error=str(exc)[:160])

        # Fallback: Playwright with WAF solver
        try:
            results = await self._fetch_with_playwright()
        except Exception as exc:
            log.warning("nc_unclaimed.playwright_failed", error=str(exc)[:160])

        return results

    async def _fetch_with_playwright(self) -> list[Listing]:
        """Use Playwright to render the SPA, solve Turnstile, and search."""
        results: list[Listing] = []
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("nc_unclaimed.no_playwright")
            return results

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )
            page = await browser.new_page()

            # Capture API responses
            api_responses: list[dict] = []

            async def handle_response(response):
                if "/SWS/properties" in response.url and response.status == 200:
                    try:
                        data = await response.json()
                        api_responses.append(data)
                    except Exception:
                        pass

            page.on("response", handle_response)

            await page.goto(_URL, timeout=45000)

            # Try WAF solver for Turnstile
            try:
                from ...enrichment_waf_oss import solve_waf_via_browser
                solved = await solve_waf_via_browser(page)
                if solved:
                    log.info("nc_unclaimed.turnstile_solved")
                    await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception as exc:
                log.warning("nc_unclaimed.waf_error", error=str(exc)[:160])

            # Search for each surname
            for surname in _SEARCH_NAMES:
                try:
                    # Wait for search form to appear
                    last_name_input = page.locator(
                        "input[name*='lastName'], input[name*='LastName'], "
                        "input[placeholder*='Last'], input[id*='lastName'], "
                        "input[id*='lastname']"
                    )
                    if await last_name_input.count() > 0:
                        await last_name_input.first.fill(surname)

                        # Click search button
                        search_btn = page.locator(
                            "button:has-text('Search'), input[type='submit'], "
                            "button[type='submit']"
                        )
                        if await search_btn.count() > 0:
                            await search_btn.first.click()
                            await page.wait_for_load_state("networkidle", timeout=30000)

                    # Parse captured API response
                    for resp in api_responses:
                        results.extend(self._parse_api_response(resp, surname))

                    api_responses.clear()

                    log.info("nc_unclaimed.surname_done",
                             surname=surname, found=len(results))

                except Exception as exc:
                    log.warning("nc_unclaimed.surname_error",
                                surname=surname, error=str(exc)[:160])

            await browser.close()

        return results

    def _search_via_browser(self, html: str) -> list[Listing]:
        """Parse search results from rendered HTML."""
        results: list[Listing] = []
        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select(
            "table tr, .results tr, .grid tr, "
            ".search-result, .property-item"
        )

        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            name = cells[0].get_text(strip=True)
            addr = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            amount = cells[2].get_text(strip=True) if len(cells) > 2 else ""

            amount_val = None
            if amount:
                m = re.search(r"[\$]([\d,.]+)", amount)
                if m:
                    amount_val = float(m.group(1).replace(",", ""))

            results.append(Listing(
                source=self.slug,
                source_url=_URL,
                listing_type=ListingType.UNKNOWN,
                property_kind=PropertyKind.UNKNOWN,
                street_address=addr,
                state="NC",
                owner_name=name,
                tax_value=amount_val,
                raw={"amount": amount},
            ))

        return results

    def _parse_api_response(self, data: dict, surname: str) -> list[Listing]:
        """Parse JSON API response from /SWS/properties."""
        results: list[Listing] = []
        items = data.get("items") or data.get("properties") or data.get("results") or []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("ownerName") or item.get("name") or ""
                addr = item.get("address") or item.get("address1") or ""
                amount = item.get("amount") or item.get("amountText") or ""
                amount_val = None
                if isinstance(amount, (int, float)):
                    amount_val = float(amount)
                elif amount:
                    m = re.search(r"[\$]?([\d,.]+)", str(amount))
                    if m:
                        amount_val = float(m.group(1).replace(",", ""))

                results.append(Listing(
                    source=self.slug,
                    source_url=_URL,
                    listing_type=ListingType.UNKNOWN,
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=addr,
                    state="NC",
                    owner_name=name,
                    tax_value=amount_val,
                    raw={"surname_searched": surname, "amount": str(amount)},
                ))
        return results
