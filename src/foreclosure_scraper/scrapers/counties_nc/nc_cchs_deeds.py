"""NC Courthouse Computer Systems deeds — Cloudflare-walled.

gastonnc.courthousecomputersystems.com and similar host deed search for
multiple NC counties behind Cloudflare "Just a moment" challenge.

The enrichment_gaston_rod module proves curl_cffi can reach these sites
with Chrome TLS impersonation. We use the same approach here.

Counties: Gaston, Alleghany, Caldwell, Franklin, Hertford, Gates
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

_BASE = "https://{subdomain}.courthousecomputersystems.com"

_COUNTY_SITES = {
    "gaston": {"subdomain": "gastonnc", "state": "NC"},
    "alleghany": {"subdomain": "alleghanync", "state": "NC"},
    "caldwell": {"subdomain": "caldwellnc", "state": "NC"},
    "franklin": {"subdomain": "franklinnc", "state": "NC"},
    "hertford": {"subdomain": "hertfordnc", "state": "NC"},
    "gates": {"subdomain": "gatesnc", "state": "NC"},
}

_HDRS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
}


class NcCchsDeedsScraper(BaseScraper):
    """NC Courthouse Computer Systems deed search via curl_cffi."""

    slug = "counties_nc.nc_cchs_deeds"
    name = "NC CCHS Deeds"
    category = "rod"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []
        cutoff = (datetime.now() - timedelta(days=90)).strftime("%m/%d/%Y")
        end_date = datetime.now().strftime("%m/%d/%Y")

        for county, cfg in _COUNTY_SITES.items():
            try:
                base = _BASE.format(subdomain=cfg["subdomain"])
                search_url = f"{base}/search/?doctype=DEED&fromdate={cutoff}&todate={end_date}"

                log.info("nc_cchs.fetching", county=county)

                html = await self._fetch_page(base, search_url)

                if not html or len(html) < 500:
                    log.warning("nc_cchs.empty", county=county)
                    continue

                if "just a moment" in html.lower() or "challenge" in html.lower():
                    log.warning("nc_cchs.cloudflare_blocked", county=county)
                    continue

                soup = BeautifulSoup(html, "html.parser")
                rows = soup.select("table.results tr, table.grid tr, .search-result")

                for row in rows[1:]:
                    cells = row.find_all("td")
                    if len(cells) < 4:
                        continue

                    book_page = cells[0].get_text(strip=True)
                    filing_date = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                    doc_type = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                    grantor = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                    grantee = cells[4].get_text(strip=True) if len(cells) > 4 else ""

                    results.append(Listing(
                        source=self.slug,
                        source_url=base,
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

                log.info("nc_cchs.county_done", county=county, found=len(results))

            except Exception as exc:
                log.warning("nc_cchs.county_error", county=county, error=str(exc)[:200])

        return results

    async def _fetch_page(self, base: str, search_url: str) -> str | None:
        """Fetch page using curl_cffi with Chrome TLS impersonation.

        Uses the same 3-step session approach as enrichment_gaston_rod:
        1. GET / to get session cookie
        2. GET search page to seed session
        3. GET search results URL
        """
        try:
            from curl_cffi import requests as cc_requests

            # Step 1: seed session
            session = cc_requests.Session(impersonate="chrome")
            r = session.get(base + "/", headers=_HDRS, timeout=30,
                            allow_redirects=True)

            # Step 2: load search page
            r = session.get(search_url, headers=_HDRS, timeout=30,
                            allow_redirects=True)

            if r.status_code == 200 and len(r.text) > 500:
                return r.text

            log.warning("nc_cchs.curl_cffi_status",
                        status=r.status_code, size=len(r.text))
        except Exception as exc:
            log.warning("nc_cchs.curl_cffi_error", error=str(exc)[:160])

        # Fallback: Playwright with WAF solver
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-gpu"],
                )
                page = await browser.new_page()
                await page.goto(search_url, timeout=45000)

                try:
                    from ...enrichment_waf_oss import solve_waf_via_browser
                    solved = await solve_waf_via_browser(page)
                    if solved:
                        await page.wait_for_load_state(
                            "networkidle", timeout=20000
                        )
                except Exception as exc:
                    log.warning("nc_cchs.waf_error", error=str(exc)[:160])

                html = await page.content()
                await browser.close()

                if html and len(html) > 500:
                    return html
        except Exception as exc:
            log.warning("nc_cchs.playwright_error", error=str(exc)[:160])

        return None
