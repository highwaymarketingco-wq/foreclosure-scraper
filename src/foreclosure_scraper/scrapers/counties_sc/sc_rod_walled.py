"""SC Register of Deeds walled sites — Beaufort, Aiken, Jasper, Clarendon, Kershaw, Hampton.

Strategy: Playwright + WAF solver for Cloudflare/Turnstile. nodriver and
wall_bypass escalation fail on these sites due to orphaned chromium and
AWS WAF challenges. Go straight to Playwright.
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

_COUNTY_SITES = {
    "beaufort": {"url": "https://rod.beaufortcountysc.gov", "state": "SC"},
    "aiken": {"url": "https://rod.aikencountysc.gov", "state": "SC"},
    "jasper": {"url": "https://rod.jaspercountysc.gov", "state": "SC"},
    "clarendon": {"url": "https://rod.clarendoncountysc.gov", "state": "SC"},
    "kershaw": {"url": "https://rod.kershawcountysc.gov", "state": "SC"},
    "hampton": {"url": "https://rod.hamptoncountysc.gov", "state": "SC"},
}


class ScRodWalledScraper(BaseScraper):
    """SC ROD sites behind Cloudflare/CAPTCHA via Playwright + WAF solver."""

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

                    # Try search page first, then fallback paths
                    search_paths = [
                        f"/search?from={cutoff}&to={end_date}&type=DEED",
                        "/search",
                        "/deeds/search",
                        "/online/deeds",
                        "/",
                    ]

                    html = ""
                    for path in search_paths:
                        url = f"{base_url}{path}"
                        log.info("sc_rod_walled.fetching", county=county, path=path)
                        try:
                            await page.goto(url, timeout=30000)
                            await page.wait_for_load_state("domcontentloaded", timeout=15000)
                        except Exception:
                            continue

                        # Check for WAF / Cloudflare challenge
                        content = await page.content()
                        if ("challenge" in content.lower() or
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

                        if content and len(content) > 500:
                            html = content
                            break

                    if not html or len(html) < 500:
                        log.warning("sc_rod_walled.empty", county=county)
                        await page.close()
                        continue

                    soup = BeautifulSoup(html, "html.parser")
                    rows = soup.select("table tr, .results tr, .grid tr, .search-result")

                    county_results: list[Listing] = []
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

                        county_results.append(Listing(
                            source=self.slug,
                            source_url=base_url,
                            listing_type=ListingType.UNKNOWN,
                            property_kind=PropertyKind.UNKNOWN,
                            county=county.title(),
                            state=cfg["state"],
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
