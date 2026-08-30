"""GSA Surplus Real Property — federal surplus property for sale/auction.

The GSA's Office of Real Property Utilization and Disposal publishes
surplus federal real property available for public sale at:

  https://www.gsa.gov/about-us/organization/office-of-governmentwide-policy/
    office-of-real-property/real-property-disposal/surplus-property-available-
    for-public-sale

Properties are listed by state with address, acreage, and asking price.
GSA also publishes property listings at sale.gsa.gov.

Free, public, no login.
Slug: national.gsa_surplus
Category: reo
ListingType: REO
"""
from __future__ import annotations

import re
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

SALES_URL = "https://www.gsa.gov/real-estate/real-estate-listings"
SALES_API = "https://sapi.gsa.gov"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    "Accept": "text/html,application/json",
}


class GSASurplus(BaseScraper):
    slug = "national.gsa_surplus"
    name = "GSA Surplus Real Property"
    category = "reo"
    timeout_s = 90.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(SALES_URL, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("gsa_surplus.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 500:
            return out

        # GSA property listing pages contain address, city, state, ZIP, price
        # Parse property entries — format varies but usually includes
        # address patterns and state identifiers
        state_pattern = re.compile(r"\b(NC|SC)\b")
        addr_pattern = re.compile(
            r"(\d+\s+[A-Za-z0-9\s]+(?:St|Ave|Rd|Dr|Ln|Ct|Blvd|Hwy|Way|Cir|Pkwy|Ter)[A-Za-z\s]*)"
        )

        # Look for property blocks
        blocks = re.findall(
            r"<div[^>]*class=\"[^\"]*property[^\"]*\"[^>]*>(.*?)</div>",
            html,
            re.I | re.S,
        )

        if not blocks:
            # Fallback: parse entire page for address+state patterns
            blocks = [html]

        for block in blocks:
            states = state_pattern.findall(block)
            addrs = addr_pattern.findall(block)

            for i, st in enumerate(states):
                addr = addrs[i].strip() if i < len(addrs) else None
                if not addr and not st:
                    continue
                raw = {
                    "source_url": SALES_URL,
                    "surplus": True,
                }
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=SALES_URL,
                        listing_type=ListingType.REO,
                        street_address=addr,
                        state=st,
                        property_kind=PropertyKind.UNKNOWN,
                        raw=raw,
                    )
                )

        log.info("gsa_surplus.fetch_done", count=len(out))
        return out
