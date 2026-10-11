"""NC Unclaimed Property — nccash.gov Cloudflare Turnstile.

unclaimed.nccash.gov hosts NC's unclaimed property database behind a
Cloudflare Turnstile challenge.

Strategy: Use wall_bypass (pydoll for Turnstile auto-solve, nodriver
as fallback) to fetch the search results. Search by common surnames
associated with estate/probate properties.
"""
from __future__ import annotations

import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_OK
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_URL = "https://unclaimed.nccash.gov/Search"

# Common NC surnames for unclaimed property search
_SEARCH_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones",
    "Davis", "Miller", "Wilson", "Moore", "Taylor",
]


class NcUnclaimedScraper(BaseScraper):
    """NC Unclaimed Property — Turnstile via wall_bypass."""

    slug = "national.nc_unclaimed"
    name = "NC Unclaimed Property"
    category = "unclaimed"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        for surname in _SEARCH_NAMES:
            try:
                url = f"{_URL}?lastName={surname}"
                log.info("nc_unclaimed.fetching", surname=surname)

                html = await get_text(
                    url,
                    wall_bypass=True,
                    timeout=30.0,
                )

                if not html or len(html) < 500:
                    from ...wall_bypass import fetch_with_nodriver
                    html = await fetch_with_nodriver(url, timeout_s=45)

                if not html or len(html) < 500:
                    log.warning("nc_unclaimed.empty", surname=surname)
                    continue

                soup = BeautifulSoup(html, "html.parser")

                # Parse unclaimed property results
                rows = soup.select(
                    "table tr, .results tr, .grid tr, "
                    ".search-result, .property-item"
                )

                for row in rows[1:]:
                    cells = row.find_all("td")
                    if len(cells) < 3:
                        continue

                    name = cells[0].get_text(strip=True)
                    addr = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                    amount = cells[2].get_text(strip=True) if len(cells) > 2 else ""

                    amount_val = None
                    if amount:
                        m = re.search(r"[\$]([\d,.]+)", amount)
                        if m:
                            amount_val = float(m.group(1).replace(",", ""))

                    results.append(Listing(
                        source=self.slug,
                        source_url=_URL,
                        listing_type=ListingType.UNKNOWN,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=addr,
                        state="NC",
                        owner_name=name,
                        tax_value=amount_val,
                        raw={
                            "surname_searched": surname,
                            "amount": amount,
                        },
                    ))

                log.info("nc_unclaimed.surname_done",
                         surname=surname, found=len(results))

            except Exception as exc:
                log.warning("nc_unclaimed.surname_error",
                            surname=surname, error=str(exc)[:200])

        return results
