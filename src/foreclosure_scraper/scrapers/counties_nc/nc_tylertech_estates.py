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

        from ...wall_bypass import fetch_with_nodriver, fetch_through_walls

        try:
            log.info("nc_tylertech.fetching")

            # TylerTech portal blocks curl-cffi and httpx (403 on both tiers).
            # Go straight to nodriver (undetected Chrome).
            html = await fetch_with_nodriver(_URL, timeout_s=60)

            if not html or len(html) < 500:
                # Try full escalation as fallback
                html = await fetch_through_walls(_URL, render_first=True)

            if not html or len(html) < 500:
                log.warning("nc_tylertech.empty")
                return results

            # Check for picture CAPTCHA
            if "captcha" in html.lower() or "select all" in html.lower():
                log.info("nc_tylertech.picture_captcha_detected")

                # Try using Playwright + Gemini Vision to solve picture CAPTCHA
                try:
                    results.extend(await self._solve_with_playwright())
                except Exception as exc:
                    log.warning("nc_tylertech.captcha_solve_failed",
                                error=str(exc)[:200])
                return results

            # If we got through, parse results
            results.extend(self._parse_html(html))

            log.info("nc_tylertech.done", found=len(results))

        except Exception as exc:
            log.warning("nc_tylertech.error", error=str(exc)[:200])

        return results

    async def _solve_with_playwright(self) -> list[Listing]:
        """Solve AWS WAF picture CAPTCHA via enrichment_waf_oss solver.

        Uses the same proven solver as nc_ecourts_estates: Gemini vision
        identifies tiles in the 3x3 grid, Anthropic Claude as fallback.
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
            await page.goto(_URL, timeout=30000)

            # Use the proven WAF solver from enrichment_waf_oss
            try:
                from ...enrichment_waf_oss import solve_waf_via_browser
                solved = await solve_waf_via_browser(page)
                if solved:
                    log.info("nc_tylertech.waf_solved")
                    # Wait for page to settle after WAF solve
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    html = await page.content()
                    results.extend(self._parse_html(html))
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
