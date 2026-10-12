"""Rowan County NC deeds — Cott eSearch challenge page.

rod.rowancountync.gov/external uses a Cott Systems eSearch challenge page
before allowing access to the deed search.

Strategy: Use Playwright to render through the challenge, then search for
deeds by date range and parse results.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_URL = "https://rod.rowancountync.gov/external"


class NcRowanCottScraper(BaseScraper):
    """Rowan County NC deeds — Cott eSearch via Playwright."""

    slug = "counties_nc.nc_rowan_cott"
    name = "Rowan NC Deeds (Cott)"
    category = "rod"
    timeout_s = 300.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("nc_rowan_cott.no_playwright")
            return results

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )
            page = None
            try:
                page = await browser.new_page()
                log.info("nc_rowan_cott.fetching")

                await page.goto(_URL, timeout=30000)
                await page.wait_for_load_state("domcontentloaded", timeout=20000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                # Check for WAF/challenge
                content = await page.content()
                if ("challenge" in content.lower() or
                    "turnstile" in content.lower() or
                    "aws-waf" in content.lower()):
                    log.info("nc_rowan_cott.waf_detected")
                    try:
                        from ...enrichment_waf_oss import solve_waf_via_browser
                        solved = await solve_waf_via_browser(page)
                        if solved:
                            await page.wait_for_load_state("domcontentloaded", timeout=15000)
                            content = await page.content()
                    except Exception as exc:
                        log.warning("nc_rowan_cott.waf_failed", error=str(exc)[:160])

                if not content or len(content) < 500:
                    log.warning("nc_rowan_cott.empty")
                    await page.close()
                    await browser.close()
                    return results

                # Try to interact with search form
                cutoff = (datetime.now() - timedelta(days=90)).strftime("%m/%d/%Y")
                end_str = datetime.now().strftime("%m/%d/%Y")

                for selector in [
                    "input[name*='from'], input[name*='start'], input[name*='begdate']",
                    "input[name*='to'], input[name*='end'], input[name*='enddate']",
                ]:
                    try:
                        inputs = await page.query_selector_all(selector)
                        if len(inputs) >= 2:
                            await inputs[0].fill(cutoff)
                            await inputs[1].fill(end_str)
                            break
                    except Exception:
                        pass

                for btn_sel in [
                    "button[type='submit']",
                    "input[type='submit']",
                    "a:has-text('Search')",
                    "#btnSearch",
                ]:
                    try:
                        btn = await page.query_selector(btn_sel)
                        if btn:
                            await btn.click()
                            break
                    except Exception:
                        pass

                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                html = await page.content()
                results.extend(self._parse_html(html))

                log.info("nc_rowan_cott.done", found=len(results))

            except Exception as exc:
                log.warning("nc_rowan_cott.error", error=str(exc)[:200])
            finally:
                if page:
                    try:
                        await page.close()
                    except BaseException:
                        pass

            await browser.close()

        return results

    def _parse_html(self, html: str) -> list[Listing]:
        """Parse Cott eSearch results from HTML."""
        results: list[Listing] = []
        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select("table tr, .search-results tr, .grid tr")
        for row in rows[1:]:
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
                source_url=_URL,
                listing_type=ListingType.UNKNOWN,
                property_kind=PropertyKind.UNKNOWN,
                county="Rowan",
                state="NC",
                case_number=book_page,
                owner_name=grantee,
                plaintiff=grantor,
                raw={
                    "doc_type": doc_type,
                    "filing_date": filing_date,
                    "grantor": grantor,
                    "grantee": grantee,
                    "book_page": book_page,
                },
            ))

        return results
