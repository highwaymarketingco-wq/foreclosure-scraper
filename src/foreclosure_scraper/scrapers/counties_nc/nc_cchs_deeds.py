"""NC Courthouse Computer Systems deeds — Cloudflare-walled.

gastonnc.courthousecomputersystems.com and similar host deed search for
multiple NC counties behind Cloudflare "Just a moment" challenge.

The wall_bypass escalation (curl-cffi → pydoll → nodriver) handles Cloudflare.

Counties: Gaston, Alleghany, Caldwell, Franklin, Hertford, Gates
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...http_client import get_text
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


class NcCchsDeedsScraper(BaseScraper):
    """NC Courthouse Computer Systems deed search via wall_bypass."""

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
                html = await get_text(
                    search_url,
                    wall_bypass=True,
                    timeout=30.0,
                )

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
