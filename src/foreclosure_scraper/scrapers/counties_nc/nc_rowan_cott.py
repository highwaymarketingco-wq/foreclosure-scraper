"""Rowan County NC deeds — Cott eSearch challenge page.

rod.rowancountync.gov/external uses a Cott Systems eSearch challenge page
before allowing access to the deed search.

Strategy: Use nodriver to render through the challenge, then search for
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
    """Rowan County NC deeds — Cott eSearch via nodriver."""

    slug = "counties_nc.nc_rowan_cott"
    name = "Rowan NC Deeds (Cott)"
    category = "rod"
    timeout_s = 300.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        from ...wall_bypass import fetch_with_nodriver, fetch_through_walls

        try:
            log.info("nc_rowan_cott.fetching")
            # Cott eSearch challenge needs real browser rendering
            html = await fetch_with_nodriver(_URL, timeout_s=45)

            if not html or len(html) < 500:
                html = await fetch_through_walls(_URL, render_first=True)

            if not html or len(html) < 500:
                log.warning("nc_rowan_cott.empty")
                return results

            soup = BeautifulSoup(html, "html.parser")

            # Parse Cott eSearch results
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

            log.info("nc_rowan_cott.done", found=len(results))

        except Exception as exc:
            log.warning("nc_rowan_cott.error", error=str(exc)[:200])

        return results
