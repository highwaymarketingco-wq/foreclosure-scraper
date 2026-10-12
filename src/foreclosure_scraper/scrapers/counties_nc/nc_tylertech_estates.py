"""NC TylerTech portal estates — picture CAPTCHA.

portal-nc.tylertech.cloud/Portal uses a picture CAPTCHA (select matching
images) for estate searches.

Strategy:
1. Launch Playwright browser.
2. Navigate to the portal.
3. Try to solve the picture CAPTCHA using Gemini Vision (if available)
   or skip it and use nodriver to render the page.
4. Search for estates by date range.
5. Parse results.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_URL = "https://portal-nc.tylertech.cloud/Portal"


class NcTylerTechEstatesScraper(BaseScraper):
    """NC TylerTech portal estates — picture CAPTCHA."""

    slug = "counties_nc.nc_tylertech_estates"
    name = "NC TylerTech Estates"
    category = "probate"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            log.info("nc_tylertech.fetching")

            # TylerTech portal has AWS WAF. nodriver and curl-cffi both get 403.
            # Go straight to Playwright + WAF solver (proven path).
            results.extend(await self._solve_with_playwright())

            log.info("nc_tylertech.done", found=len(results))

        except Exception as exc:
            log.warning("nc_tylertech.error", error=str(exc)[:200])

        return results

    async def _solve_with_playwright(self) -> list[Listing]:
        """Solve AWS WAF picture CAPTCHA via enrichment_waf_oss solver.

        Uses the same proven solver as nc_ecourts_estates: Gemini vision
        identifies tiles in the 3x3 grid, Anthropic Claude as fallback.
        After WAF is solved, navigates to estate search and submits query.
        """
        results: list[Listing] = []
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("nc_tylertech.no_playwright")
            return results

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )
            page = await browser.new_page()
            await page.goto(_URL, timeout=45000)

            # Use the proven WAF solver from enrichment_waf_oss
            try:
                from ...enrichment_waf_oss import solve_waf_via_browser
                solved = await solve_waf_via_browser(page)
                if solved:
                    log.info("nc_tylertech.waf_solved")
                    # Wait for page to settle after WAF solve
                    await page.wait_for_load_state("networkidle", timeout=20000)

                    # Now we need to navigate to estate search.
                    # TylerTech portal has a search form — try to find and
                    # submit it for estate cases.
                    results.extend(await self._search_estates(page))
                else:
                    log.warning("nc_tylertech.waf_solve_failed")
            except Exception as exc:
                log.warning("nc_tylertech.waf_error",
                            error=str(exc)[:160])
                # Try to get whatever content is on the page anyway
                html = await page.content()
                results.extend(self._parse_html(html))

            await browser.close()

        return results

    async def _search_estates(self, page) -> list[Listing]:
        """Navigate the TylerTech portal to search for estate cases."""
        results: list[Listing] = []
        try:
            html = await page.content()

            # Look for estate/probate search links or tabs
            # TylerTech portals typically have navigation links
            estate_links = page.locator("a:has-text('Estate'), a:has-text('Probate'), a:has-text('estate'), a:has-text('probate')")
            if await estate_links.count() > 0:
                await estate_links.first.click()
                await page.wait_for_load_state("networkidle", timeout=20000)
                html = await page.content()

            # Look for search form — try to fill date range and submit
            # Estate searches typically need a date range or case type
            date_from = page.locator("input[name*='date'], input[name*='Date'], input[name*='from'], input[name*='From'], #dateFrom, #fromDate")
            date_to = page.locator("input[name*='to'], input[name*='To'], #dateTo, #toDate")

            if await date_from.count() > 0:
                # Set date range to last 2 years
                from datetime import datetime, timedelta
                end = datetime.now()
                start = end - timedelta(days=730)
                await date_from.first.fill(start.strftime("%m/%d/%Y"))
                if await date_to.count() > 0:
                    await date_to.first.fill(end.strftime("%m/%d/%Y"))

            # Look for case type selector and choose Estate
            case_type = page.locator("select[name*='case'], select[name*='Case'], select[name*='type'], select[name*='Type']")
            if await case_type.count() > 0:
                try:
                    await case_type.first.select_option(label=page.locator("select option:has-text('Estate'), select option:has-text('Probate')").first)
                except Exception:
                    pass  # May not be a select or may not have estate option

            # Click search button
            search_btn = page.locator("button:has-text('Search'), input[type='submit'], button:has-text('search'), a:has-text('Search')")
            if await search_btn.count() > 0:
                await search_btn.first.click()
                await page.wait_for_load_state("networkidle", timeout=30000)
                html = await page.content()

            results.extend(self._parse_html(html))

            # Check for pagination
            next_btn = page.locator("a:has-text('Next'), a:has-text('next'), li.next a")
            page_num = 0
            while await next_btn.count() > 0 and page_num < 50:
                page_num += 1
                try:
                    await next_btn.first.click()
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    html = await page.content()
                    new_results = self._parse_html(html)
                    if not new_results:
                        break
                    results.extend(new_results)
                    next_btn = page.locator("a:has-text('Next'), a:has-text('next'), li.next a")
                except Exception:
                    break

        except Exception as exc:
            log.warning("nc_tylertech.search_error", error=str(exc)[:160])

        return results

    def _parse_html(self, html: str) -> list[Listing]:
        """Parse estate search results."""
        results: list[Listing] = []
        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select("table tr, .results tr, .grid-view tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            case_num = cells[0].get_text(strip=True)
            decedent = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            filed_date = cells[2].get_text(strip=True) if len(cells) > 2 else ""

            if not case_num:
                continue

            results.append(Listing(
                source=self.slug,
                source_url=_URL,
                listing_type=ListingType.PROBATE_NOTICE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                case_number=case_num,
                owner_name=decedent,
                raw={
                    "filed_date": filed_date,
                    "decedent": decedent,
                },
            ))

        return results
