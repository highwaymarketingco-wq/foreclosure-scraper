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

_URL = "https://unclaimed.nccash.gov/app/claim-search"
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
        """Use Playwright to render the SPA, capture Turnstile token, call API directly."""
        results: list[Listing] = []
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("nc_unclaimed.no_playwright")
            return results

        import asyncio
        import httpx

        import os
        # Use non-headless if Xvfb is available (Turnstile requires interaction)
        xvfb = os.environ.get("DISPLAY", "")
        headless = not bool(xvfb)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = await ctx.new_page()

            # Capture console messages for debugging
            page.on("console", lambda msg: log.debug("nc_unclaimed.console",
                                                     level=msg.type, text=msg.text[:200]))

            await page.goto(_URL, timeout=60000)

            # Wait for Angular to bootstrap and Turnstile to load
            await asyncio.sleep(8)

            # Wait for turnstile object to be available
            try:
                await page.wait_for_function(
                    "() => typeof turnstile !== 'undefined'",
                    timeout=15000,
                )
            except Exception:
                log.warning("nc_unclaimed.no_turnstile_obj")
                await browser.close()
                return results

            # Execute Turnstile and get token
            token = None
            for attempt in range(3):
                try:
                    token = await page.evaluate("""() => {
                        // Try to get existing token
                        try { let t = turnstile.getResponse(); if (t && t.length > 10) return t; } catch(e) {}
                        // Try to get from hidden field
                        const el = document.querySelector('[name="cf-turnstile-response"]');
                        if (el && el.value && el.value.length > 10) return el.value;
                        // Try execute with proper params
                        const widgets = document.querySelectorAll('[id^="cf-chl-widget"]');
                        if (widgets.length > 0) {
                            try { turnstile.execute(widgets[0].id, {action: 'submit'}); } catch(e) {}
                        }
                        // Also try clicking the SEARCH button to trigger Turnstile callback
                        const btns = document.querySelectorAll('button');
                        for (const b of btns) {
                            if (b.innerText && b.innerText.toUpperCase().includes('SEARCH')) {
                                try { b.click(); } catch(e) {}
                                break;
                            }
                        }
                        return null;
                    }""")
                    if token and len(token) > 10:
                        break
                    # Wait for callback to fire after clicking SEARCH
                    await asyncio.sleep(8)
                    token = await page.evaluate("""() => {
                        try { let t = turnstile.getResponse(); if (t && t.length > 10) return t; } catch(e) {}
                        const el = document.querySelector('[name="cf-turnstile-response"]');
                        if (el && el.value && el.value.length > 10) return el.value;
                        return null;
                    }""")
                    if token and len(token) > 10:
                        break
                except Exception as exc:
                    log.warning("nc_unclaimed.turnstile_exec_failed",
                                attempt=attempt + 1, error=str(exc)[:160])
                    await asyncio.sleep(3)

            if not token or len(token) < 10:
                log.warning("nc_unclaimed.no_token")
                await browser.close()
                return results

            log.info("nc_unclaimed.token_captured", token_len=len(token))

            # Now make direct API calls with the token
            async with httpx.AsyncClient() as client:
                for surname in _SEARCH_NAMES:
                    try:
                        resp = await client.post(
                            _API,
                            json={
                                "lastName": surname,
                                "firstName": "",
                                "city": "",
                                "searchZipCode": "",
                                "propertyID": "",
                                "cf-turnstile-response": token,
                            },
                            headers={
                                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                                "Origin": "https://unclaimed.nccash.gov",
                                "Referer": "https://unclaimed.nccash.gov/app/claim-search",
                                "Content-Type": "application/json",
                            },
                            timeout=30,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            found = self._parse_api_response(data, surname)
                            results.extend(found)
                            log.info("nc_unclaimed.surname_done",
                                     surname=surname, found=len(found),
                                     status=resp.status_code)
                        else:
                            log.warning("nc_unclaimed.api_error",
                                        surname=surname,
                                        status=resp.status_code,
                                        body=resp.text[:200])
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
