"""NC Register of Deeds sites with CAPTCHA/math gate — 9 counties.

ALL 9 URLS REWRITTEN 2026-10-12. Before this date only 2 of 9 (Brunswick,
Stokes) had ever been checked against a live site -- the other 7 had never
actually been verified, and every single one was dead: 5 hard DNS failures
(Iredell, Craven, Greene, Harnett, Randolph -- "Could not resolve host",
confirmed from two separate networks) plus Wake (404 -- the domain itself
was right, the code was just missing the real `/web` app path) and Durham
(the whole county domain family changed to dconc.gov). The old docstring's
gate-type claims below were therefore also unverified guesses in several
cases, not confirmed observations -- corrected where live evidence now
exists.

Sites and gate types (all confirmed live 2026-10-12 unless noted):
- rodrecords.wake.gov/web — real Google reCAPTCHA checkbox, confirmed by
  screenshot (Tyler Technologies "Self-Service" platform v2026.1.5). Old
  code hit the bare domain (404); the app lives under /web.
- rodweb.dconc.gov/web — Durham's new domain (county migrated away from
  durhamcountync.gov entirely). Same Tyler "Self-Service" platform as
  Wake -- gate very likely the same reCAPTCHA, not individually
  screenshotted.
- brunswick-live.inttek.net — math question, confirmed by screenshot
  ("Four Minus One Equals ___"), use math_captcha.py. Real post-gate
  search_path still unverified (gate itself not cleared).
- iredellnc.courthousecomputersystems.com — real Google reCAPTCHA,
  confirmed by screenshot ("Please Verify You are Not a Robot"). NOTE:
  this platform only covers records from 1964 forward; pre-1964 records
  need a second, separate system (cotthosting.com/NCIredellExternal) --
  out of scope for now, flagging it exists.
- greenenc.courthousecomputersystems.com — same Courthouse Computer
  Systems platform as Stokes/Iredell (both confirmed reCAPTCHA); this
  county's own site says the system went live Dec 2025. High-confidence
  reCAPTCHA by platform match, not individually screenshotted.
- us6.courthousecomputersystems.com/HarnettNC — SAME base domain as
  Stokes, just a different county path (shared multi-tenant platform).
  High-confidence reCAPTCHA by platform match.
- us5.courthousecomputersystems.com/RandolphNC2 — different server
  instance (us5, not us6) and an unexpected "2" suffix on the county
  code. Owner directly observed CAPTCHA + disclaimer live 2026-10-12 --
  this corrects the old docstring's "math question" guess, which was
  never actually verified against this (or any) live URL.
- us5.courthousecomputersystems.com/CravenNC2 — same us5 instance as
  Randolph. Same correction: owner-confirmed CAPTCHA + disclaimer live
  2026-10-12, not the old docstring's unverified "math question" guess.
- us6.courthousecomputersystems.com/StokesNC — real Google reCAPTCHA,
  confirmed by screenshot, behind a terms-of-use disclaimer.

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
    "wake": {"url": "https://rodrecords.wake.gov/web", "gate": "recaptcha", "search_path": "/user/disclaimer"},
    "durham": {"url": "https://rodweb.dconc.gov/web", "gate": "recaptcha", "search_path": "/user/disclaimer"},
    "brunswick": {"url": "https://brunswick-live.inttek.net", "gate": "math", "search_path": "/search"},
    "iredell": {"url": "https://iredellnc.courthousecomputersystems.com", "gate": "recaptcha", "search_path": "/search"},
    "craven": {"url": "https://us5.courthousecomputersystems.com/CravenNC2", "gate": "recaptcha", "search_path": "/search"},
    "greene": {"url": "https://greenenc.courthousecomputersystems.com", "gate": "recaptcha", "search_path": "/search"},
    "harnett": {"url": "https://us6.courthousecomputersystems.com/HarnettNC", "gate": "recaptcha", "search_path": "/search"},
    "randolph": {"url": "https://us5.courthousecomputersystems.com/RandolphNC2", "gate": "recaptcha", "search_path": "/search"},
    "stokes": {"url": "https://us6.courthousecomputersystems.com/StokesNC", "gate": "recaptcha", "search_path": "/search"},
}


class NcRodCaptchaScraper(BaseScraper):
    """NC ROD sites with CAPTCHA/math gate — Playwright + auto-solver."""

    slug = "counties_nc.nc_rod_captcha"
    name = "NC ROD CAPTCHA Sites"
    category = "rod"
    timeout_s = 900.0

    async def fetch(self) -> list[Listing]:
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
                        log.info("nc_rod_captcha.gate_failed_try_waf", county=county)
                        try:
                            from ...enrichment_waf_oss import solve_waf_via_browser
                            gate_cleared = await solve_waf_via_browser(page)
                        except Exception as exc:
                            log.warning("nc_rod_captcha.waf_failed", county=county, error=str(exc)[:160])
                        if gate_cleared:
                            await page.wait_for_load_state("domcontentloaded", timeout=15000)
                        else:
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
                        except BaseException:
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
