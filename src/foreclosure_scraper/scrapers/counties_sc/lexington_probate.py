"""Lexington County SC probate search — reCAPTCHA V2 (returns HTTP 401).

www.lex-co.com/ProbateSearch/estates uses reCAPTCHA V2 in explicit render mode.
Without solving it, the server returns HTTP 401.

Strategy:
1. Launch Playwright browser.
2. Navigate to the probate search page.
3. Use enrichment_recaptcha_audio.solve_recaptcha_v2(page) to clear reCAPTCHA.
4. Once cleared, search for estates by date range.
5. Parse the results table.
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

_URL = "https://www.lex-co.com/ProbateSearch/estates"


class LexingtonProbateScraper(BaseScraper):
    """Lexington County SC probate search — reCAPTCHA V2 audio solver."""

    slug = "counties_sc.lexington_probate"
    name = "Lexington SC Probate"
    category = "probate"
    timeout_s = 300.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("lexington_probate.no_playwright")
            return results

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )
            page = await browser.new_page()

            try:
                log.info("lexington_probate.loading")
                await page.goto(_URL, timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=10000)

                # Solve reCAPTCHA V2
                try:
                    from ...enrichment_recaptcha_audio import solve_recaptcha_v2
                    solved = await solve_recaptcha_v2(page)
                except Exception as exc:
                    log.warning("lexington_probate.recaptcha_failed",
                                error=str(exc)[:200])
                    solved = False

                if not solved:
                    # Try wall_bypass nodriver as fallback
                    log.info("lexington_probate.trying_nodriver")
                    from ...wall_bypass import fetch_with_nodriver
                    html = await fetch_with_nodriver(_URL, timeout_s=45)
                    if html and len(html) > 500:
                        results.extend(self._parse_html(html))
                    await browser.close()
                    return results

                # Search for estates — leave fields blank for all results
                # or set a date range
                cutoff = (datetime.now() - timedelta(days=365))
                cutoff_str = cutoff.strftime("%m/%d/%Y")

                # Try to fill date field
                for sel in [
                    "input[name*='date'], input[name*='from'], input[name*='start']",
                    "#dateFrom, #fromDate",
                ]:
                    try:
                        el = await page.query_selector(sel)
                        if el:
                            await el.fill(cutoff_str)
                            break
                    except Exception:
                        pass

                # Click search button
                for btn_sel in [
                    "button:has-text('Search')",
                    "input[type='submit']",
                    "a:has-text('Search')",
                    "#btnSearch, #searchButton",
                ]:
                    try:
                        btn = await page.query_selector(btn_sel)
                        if btn:
                            await btn.click()
                            break
                    except Exception:
                        pass

                await page.wait_for_load_state("networkidle", timeout=15000)

                # Parse results
                html = await page.content()
                results.extend(self._parse_html(html))

                log.info("lexington_probate.done", found=len(results))

            except Exception as exc:
                log.warning("lexington_probate.error",
                            error=str(exc)[:200])
            finally:
                await browser.close()

        return results

    def _parse_html(self, html: str) -> list[Listing]:
        """Parse probate estate results."""
        results: list[Listing] = []
        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select(
            "table tr, .results tr, .grid-view tr, .data-table tr"
        )
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            case_num = cells[0].get_text(strip=True)
            decedent = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            filed_date = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            status = cells[3].get_text(strip=True) if len(cells) > 3 else ""

            if not case_num or not decedent:
                continue

            results.append(Listing(
                source=self.slug,
                source_url=_URL,
                listing_type=ListingType.PROBATE_NOTICE,
                property_kind=PropertyKind.UNKNOWN,
                county="Lexington",
                state="SC",
                case_number=case_num,
                owner_name=decedent,
                raw={
                    "filed_date": filed_date,
                    "status": status,
                    "decedent": decedent,
                },
            ))

        return results
