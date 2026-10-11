"""NC Register of Deeds sites with CAPTCHA/math gate — 9 counties.

Sites and gate types:
- rodrecords.wake.gov — Google CAPTCHA on entry
- rodrecords.durhamcountync.gov — Google CAPTCHA
- rodrecords.brunswickcountync.gov — math question (use math_captcha.py)
- rod.iredellcountync.gov — Google CAPTCHA
- rod.cravencountync.gov — math question
- rod.greenecountync.gov — Google CAPTCHA
- rod.harnettcountync.gov — Google CAPTCHA
- rod.randolphcountync.gov — math question
- rod.stokescountync.gov — Google CAPTCHA

Strategy:
1. Launch Playwright browser (headless on VM).
2. Navigate to the entry/disclaimer page.
3. If math captcha: use math_captcha.solve_math_captcha(page)
4. If reCAPTCHA V2: use enrichment_recaptcha_audio.solve_recaptcha_v2(page)
5. Once through, search for deeds by date range.
6. Parse results.
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
    "wake": {"url": "https://rodrecords.wake.gov", "gate": "recaptcha", "search_path": "/search/deeds"},
    "durham": {"url": "https://rodrecords.durhamcountync.gov", "gate": "recaptcha", "search_path": "/search/deeds"},
    "brunswick": {"url": "https://rodrecords.brunswickcountync.gov", "gate": "math", "search_path": "/search"},
    "iredell": {"url": "https://rod.iredellcountync.gov", "gate": "recaptcha", "search_path": "/search"},
    "craven": {"url": "https://rod.cravencountync.gov", "gate": "math", "search_path": "/search"},
    "greene": {"url": "https://rod.greenecountync.gov", "gate": "recaptcha", "search_path": "/search"},
    "harnett": {"url": "https://rod.harnettcountync.gov", "gate": "recaptcha", "search_path": "/search"},
    "randolph": {"url": "https://rod.randolphcountync.gov", "gate": "math", "search_path": "/search"},
    "stokes": {"url": "https://rod.stokescountync.gov", "gate": "recaptcha", "search_path": "/search"},
}


class NcRodCaptchaScraper(BaseScraper):
    """NC ROD sites with CAPTCHA/math gate — Playwright + auto-solver."""

    slug = "counties_nc.nc_rod_captcha"
    name = "NC ROD CAPTCHA Sites"
    category = "rod"
    timeout_s = 900.0

    async def _collect(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("nc_rod_captcha.no_playwright")
            return results

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )

            for county, cfg in _COUNTY_SITES.items():
                page = None
                try:
                    page = await browser.new_page()
                    entry_url = cfg["url"]
                    log.info("nc_rod_captcha.fetching", county=county)

                    await page.goto(entry_url, timeout=30000)
                    await page.wait_for_load_state("networkidle", timeout=10000)

                    gate = cfg["gate"]
                    gate_cleared = False

                    if gate == "math":
                        try:
                            from ...math_captcha import solve_math_captcha
                            gate_cleared = await solve_math_captcha(page)
                        except Exception as exc:
                            log.warning("nc_rod_captcha.math_failed", county=county, error=str(exc)[:160])

                    elif gate == "recaptcha":
                        try:
                            from ...enrichment_recaptcha_audio import solve_recaptcha_v2
                            gate_cleared = await solve_recaptcha_v2(page)
                        except Exception as exc:
                            log.warning("nc_rod_captcha.recaptcha_failed", county=county, error=str(exc)[:160])

                    if not gate_cleared:
                        log.info("nc_rod_captcha.gate_failed_try_bypass", county=county)
                        from ...wall_bypass import fetch_through_walls
                        html = await fetch_through_walls(
                            f"{entry_url}{cfg['search_path']}",
                            render_first=False,
                        )
                        if html and len(html) > 500:
                            results.extend(self._parse_html(html, county, entry_url))
                            await page.close()
                            continue
                        log.warning("nc_rod_captcha.gate_blocked", county=county)
                        await page.close()
                        continue

                    search_url = f"{entry_url}{cfg['search_path']}"
                    await page.goto(search_url, timeout=30000)

                    cutoff = (datetime.now() - timedelta(days=90))
                    cutoff_str = cutoff.strftime("%m/%d/%Y")
                    end_str = datetime.now().strftime("%m/%d/%Y")

                    for selector in [
                        "input[name*='from'], input[name*='start'], input[name*='begdate']",
                        "input[name*='to'], input[name*='end'], input[name*='enddate']",
                    ]:
                        try:
                            inputs = await page.query_selector_all(selector)
                            if len(inputs) >= 2:
                                await inputs[0].fill(cutoff_str)
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

                    await page.wait_for_load_state("networkidle", timeout=15000)

                    html = await page.content()
                    results.extend(self._parse_html(html, county, entry_url))

                    await page.close()
                    log.info("nc_rod_captcha.county_done", county=county, found=len(results))

                except Exception as exc:
                    log.warning("nc_rod_captcha.county_error", county=county, error=str(exc)[:200])
                    if page:
                        try:
                            await page.close()
                        except Exception:
                            pass

            await browser.close()

        return results

    def _parse_html(self, html: str, county: str, base_url: str) -> list[Listing]:
        """Parse deed search results from HTML."""
        results: list[Listing] = []
        soup = BeautifulSoup(html, "html.parser")

        rows = soup.select("table.results tr, table.grid tr, .search-result, table tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            book_page = cells[0].get_text(strip=True)
            filing_date = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            doc_type = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            grantor = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            grantee = cells[4].get_text(strip=True) if len(cells) > 4 else ""

            if not book_page or book_page == "\xa0":
                continue

            results.append(Listing(
                source=self.slug,
                source_url=base_url,
                listing_type=ListingType.UNKNOWN,
                property_kind=PropertyKind.UNKNOWN,
                county=county.title(),
                state="NC",
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
