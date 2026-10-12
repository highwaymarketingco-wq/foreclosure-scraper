"""NC Unclaimed Property — nccash.gov Cloudflare Turnstile.

unclaimed.nccash.gov hosts NC's unclaimed property database behind a
Cloudflare Turnstile challenge. The Angular SPA calls POST /SWS/properties
with a Turnstile token.

Strategy: Playwright renders the SPA. Turnstile in managed mode auto-solves
without user interaction — we just wait for the page to settle. The Angular
app makes XHR calls to /SWS/properties — we intercept those responses.
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
    """NC Unclaimed Property — Turnstile auto-solve via Playwright."""

    slug = "national.nc_unclaimed"
    name = "NC Unclaimed Property"
    category = "unclaimed"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            results = await self._fetch_with_playwright()
        except BaseException as exc:
            log.warning("nc_unclaimed.playwright_failed", error=str(exc)[:160])

        return results

    async def _fetch_with_playwright(self) -> list[Listing]:
        """Use Playwright to render the SPA. Turnstile auto-solves in managed mode."""
        results: list[Listing] = []
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("nc_unclaimed.no_playwright")
            return results

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
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

            await page.goto(_URL, timeout=60000)

            # Turnstile managed mode auto-solves — just wait for SPA to settle.
            # Give the Angular app time to bootstrap and Turnstile to clear.
            try:
                await page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass  # networkidle may not fire if Turnstile keeps a connection open

            # Wait a bit more for Angular to render the search form
            import asyncio
            await asyncio.sleep(5)

            # Debug: log page state
            try:
                page_url = page.url
                page_title = await page.title()
                # Count visible inputs
                input_count = await page.locator("input").count()
                button_count = await page.locator("button").count()
                log.info("nc_unclaimed.page_state",
                         url=page_url, title=page_title,
                         inputs=input_count, buttons=button_count)
                # Log all input names/ids
                inputs_info = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('input')).map(i => ({
                        name: i.name, id: i.id, type: i.type,
                        placeholder: i.placeholder,
                        class: i.className
                    }))
                }""")
                log.info("nc_unclaimed.inputs", inputs=inputs_info)
                # Log all button texts
                buttons_info = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('button')).map(b => ({
                        text: b.innerText, type: b.type, class: b.className
                    }))
                }""")
                log.info("nc_unclaimed.buttons", buttons=buttons_info)
            except Exception as exc:
                log.warning("nc_unclaimed.debug_failed", error=str(exc)[:160])

            # Search for each surname
            for surname in _SEARCH_NAMES:
                try:
                    # Wait for search form — try multiple selectors
                    last_name_input = page.locator(
                        "input[name*='lastName'], input[name*='LastName'], "
                        "input[placeholder*='Last'], input[id*='lastName'], "
                        "input[id*='lastname'], input[formcontrolname*='name']"
                    )
                    if await last_name_input.count() > 0:
                        await last_name_input.first.fill(surname)

                        # Click search button
                        search_btn = page.locator(
                            "button:has-text('Search'), input[type='submit'], "
                            "button[type='submit'], .search-btn, "
                            "button:has-text('SEARCH')"
                        )
                        if await search_btn.count() > 0:
                            await search_btn.first.click()
                            # Wait for API response
                            import asyncio
                            await asyncio.sleep(3)
                            try:
                                await page.wait_for_load_state("networkidle", timeout=15000)
                            except Exception:
                                pass

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
