"""SC Register of Deeds walled sites — Beaufort, Jasper, Clarendon.

Beaufort: rod.beaufortcountysc.gov/BrowserViewDMP/ — Angular SPA, no WAF.
Jasper: us6.courthousecomputersystems.com/jasperSC — Cloudflare 403, needs WAF solver.
Clarendon: acclaimprod.clarendoncountygov.org/acclaimweb — Cloudflare 403, needs WAF solver.

Aiken, Kershaw, Hampton: DNS dead — removed.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_COUNTY_SITES = {
    "beaufort": {
        "url": "https://rod.beaufortcountysc.gov/BrowserViewDMP/",
        "state": "SC",
        "walled": False,
    },
    "jasper": {
        "url": "https://us6.courthousecomputersystems.com/jasperSC",
        "state": "SC",
        "walled": True,
    },
    "clarendon": {
        "url": "https://acclaimprod.clarendoncountygov.org/acclaimweb",
        "state": "SC",
        "walled": True,
    },
}


class ScRodWalledScraper(BaseScraper):
    """SC ROD sites — Beaufort (direct), Jasper/Clarendon (Cloudflare)."""

    slug = "counties_sc.sc_rod_walled"
    name = "SC ROD Walled Sites"
    category = "rod"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("sc_rod_walled.no_playwright")
            return results

        cutoff = (datetime.now() - timedelta(days=90)).strftime("%m/%d/%Y")
        end_date = datetime.now().strftime("%m/%d/%Y")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )

            for county, cfg in _COUNTY_SITES.items():
                page = None
                try:
                    page = await browser.new_page()
                    base_url = cfg["url"]

                    log.info("sc_rod_walled.fetching", county=county, url=base_url)

                    # Beaufort: ignore SSL cert (expired cert)
                    if county == "beaufort":
                        context = await browser.new_context(
                            ignore_https_errors=True,
                        )
                        page = await context.new_page()

                    await page.goto(base_url, timeout=45000)
                    await page.wait_for_load_state("domcontentloaded", timeout=20000)

                    # Check for WAF / Cloudflare challenge
                    content = await page.content()
                    if (cfg.get("walled") or
                        "challenge" in content.lower() or
                        "turnstile" in content.lower() or
                        "aws-waf" in content.lower() or
                        "captcha" in content.lower()):
                        log.info("sc_rod_walled.waf_detected", county=county)
                        try:
                            from ...enrichment_waf_oss import solve_waf_via_browser
                            solved = await solve_waf_via_browser(page)
                            if solved:
                                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                                content = await page.content()
                        except Exception as exc:
                            log.warning("sc_rod_walled.waf_failed", county=county, error=str(exc)[:160])

                    if not content or len(content) < 500:
                        log.warning("sc_rod_walled.empty", county=county)
                        continue

                    # These are all Angular/SPA search portals
                    # Try to interact with the search form
                    county_results = await self._search_records(
                        page, base_url, county, cfg["state"], cutoff, end_date
                    )
                    results.extend(county_results)
                    log.info("sc_rod_walled.county_done", county=county, found=len(county_results))

                except Exception as exc:
                    log.warning("sc_rod_walled.county_error", county=county, error=str(exc)[:200])
                finally:
                    if page:
                        try:
                            await page.close()
                        except BaseException:
                            pass

            await browser.close()

        return results

    async def _search_records(
        self, page, base_url: str, county: str, state: str,
        cutoff: str, end_date: str,
    ) -> list[Listing]:
        """Search for deed records in the SPA and parse results."""
        results: list[Listing] = []
        import json

        # Wait for SPA to load
        await asyncio.sleep(3)

        # Debug: log page state
        try:
            inputs_info = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('input, button, a.btn')).map(i => ({
                    tag: i.tagName, name: i.name, id: i.id, type: i.type,
                    text: i.innerText || i.value || '', placeholder: i.placeholder
                }))
            }""")
            log.info("sc_rod_walled.page_state", county=county,
                      url=page.url, elements=inputs_info)
        except Exception as exc:
            log.warning("sc_rod_walled.debug_failed", county=county, error=str(exc)[:160])

        # Try to find and fill date range / search form
        # Beaufort BrowserView: has date pickers and a Search button
        # Jasper/Clarendon: Courthouse Computer Systems / Acclaim portals

        # First, try clicking a "90 Days" quick button via JS (Beaufort has these)
        quick_clicked = await page.evaluate("""() => {
            const btns = document.querySelectorAll('button, a, input[type="submit"]');
            for (const b of btns) {
                const t = (b.innerText || b.value || '').trim();
                if (t === '90 Days' || t === '30 Days' || t === '7 Days') {
                    b.click();
                    return t;
                }
            }
            return null;
        }""")
        if quick_clicked:
            log.info("sc_rod_walled.quick_btn", county=county, selector=quick_clicked)
            await asyncio.sleep(5)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            content = await page.content()
            return self._parse_results(content, page.url, county, state)

        # Fill date inputs via JS (Angular inputs may not be Playwright-visible)
        filled = await page.evaluate("""(args) => {
            const [cutoff, end] = args;
            let fromSet = false, toSet = false;
            // Set fromdate
            const fromEl = document.querySelector('input[name="fromdate"]')
                || document.querySelector('input[name*="from" i]');
            if (fromEl) {
                fromEl.value = cutoff;
                fromEl.dispatchEvent(new Event('input', {bubbles: true}));
                fromEl.dispatchEvent(new Event('change', {bubbles: true}));
                fromSet = true;
            }
            // Set todate
            const toEl = document.querySelector('input[name="todate"]')
                || document.querySelector('input[name*="to" i]');
            if (toEl) {
                toEl.value = end;
                toEl.dispatchEvent(new Event('input', {bubbles: true}));
                toEl.dispatchEvent(new Event('change', {bubbles: true}));
                toSet = true;
            }
            return {fromSet, toSet};
        }""", [cutoff, end_date])

        if filled.get("fromSet") or filled.get("toSet"):
            log.info("sc_rod_walled.dates_filled", county=county, **filled)
            # Click search button via JS
            search_clicked = await page.evaluate("""() => {
                const btns = document.querySelectorAll('button[type="submit"], input[type="submit"], button');
                for (const b of btns) {
                    const t = (b.innerText || b.value || '').trim().toLowerCase();
                    if (t === 'search') {
                        b.click();
                        return true;
                    }
                }
                return false;
            }""")
            if search_clicked:
                await asyncio.sleep(5)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                content = await page.content()
                return self._parse_results(content, page.url, county, state)
        else:
            log.info("sc_rod_walled.no_date_inputs", county=county)

        # Try to just click search with defaults
        search_clicked = await page.evaluate("""() => {
            const btns = document.querySelectorAll('button[type="submit"], input[type="submit"], button');
            for (const b of btns) {
                const t = (b.innerText || b.value || '').trim().toLowerCase();
                if (t === 'search') {
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
        if search_clicked:
            await asyncio.sleep(5)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

        # Parse results from table or grid
        content = await page.content()
        return self._parse_results(content, page.url, county, state)

    def _parse_results(self, content: str, base_url: str,
                       county: str, state: str) -> list[Listing]:
        """Parse search results HTML into listings."""
        results: list[Listing] = []
        soup = BeautifulSoup(content, "html.parser")

        # Try various result table selectors
        rows = soup.select(
            "table tr, .results tr, .grid tr, .search-result, "
            ".data-row, .result-item, [ng-repeat] tr"
        )

        for row in rows[1:]:  # skip header
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            book_page = cells[0].get_text(strip=True)
            filing_date = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            doc_type = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            grantor = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            grantee = cells[4].get_text(strip=True) if len(cells) > 4 else ""

            if not book_page:
                continue

            results.append(Listing(
                source=self.slug,
                source_url=base_url,
                listing_type=ListingType.UNKNOWN,
                property_kind=PropertyKind.UNKNOWN,
                county=county.title(),
                state=state,
                case_number=book_page,
                owner_name=grantee,
                plaintiff=grantor,
                raw={
                    "county": county,
                    "doc_type": doc_type,
                    "filing_date": filing_date,
                    "grantor": grantor,
                    "grantee": grantee,
                    "book_page": book_page,
                },
            ))

        return results
