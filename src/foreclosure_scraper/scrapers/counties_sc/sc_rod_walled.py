"""SC Register of Deeds walled sites — Beaufort, Aiken, Jasper, Clarendon, Kershaw, Hampton.

Strategy: wall_bypass escalation handles Cloudflare. For CAPTCHA,
use nodriver to render in real browser. Then parse deed results.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...http_client import client
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
    """SC ROD sites behind Cloudflare/CAPTCHA via wall_bypass."""

    slug = "counties_sc.sc_rod_walled"
    name = "SC ROD Walled Sites"
    category = "rod"
    timeout_s = 600.0

    async def _collect(self) -> list[Listing]:
        results: list[Listing] = []

        cutoff = (datetime.now() - timedelta(days=90)).strftime("%m/%d/%Y")
        end_date = datetime.now().strftime("%m/%d/%Y")

        for county, cfg in _COUNTY_SITES.items():
            try:
                base_url = cfg["url"]
                html = ""

                for path in [
                    f"/search?from={cutoff}&to={end_date}&type=DEED",
                    "/search",
                    "/deeds/search",
                    "/online/deeds",
                    "/",
                ]:
                    url = f"{base_url}{path}"
                    log.info("sc_rod_walled.fetching", county=county, path=path)
                    html = await client.get_text(url, wall_bypass=True, timeout=30.0)
                    if html and len(html) > 500:
                        break

                if not html or len(html) < 500:
                    log.warning("sc_rod_walled.empty", county=county)
                    continue

                if ("captcha" in html.lower() or
                    "g-recaptcha" in html.lower() or
                    "turnstile" in html.lower()):
                    log.info("sc_rod_walled.captcha_detected", county=county)
                    from ...wall_bypass import fetch_with_nodriver
                    html = await fetch_with_nodriver(url, timeout_s=45)
                    if not html or len(html) < 500:
                        log.warning("sc_rod_walled.nodriver_failed", county=county)
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

        return results
