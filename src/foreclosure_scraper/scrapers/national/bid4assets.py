"""Bid4Assets — county tax sale auctions."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind


class Bid4Assets(BaseScraper):
    slug = "national.bid4assets"
    name = "Bid4Assets"
    category = "national_auction"

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in ("SC", "NC"):
            url = f"https://www.bid4assets.com/storefront/index.cfm?searchstate={state}&searchprop=Real+Estate"
            try:
                html = await get_text(url, timeout=45.0)
            except Exception:
                continue
            tree = HTMLParser(html)
            for a in tree.css("a[href*='auction']"):
                href = a.attributes.get("href", "")
                if not href or "auction" not in href.lower():
                    continue
                if href.startswith("/"):
                    href = f"https://www.bid4assets.com{href}"
                title = a.text(strip=True)
                if not title:
                    continue
                # Try to pull county out of the link text
                m = re.search(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s+County\b", title)
                county = m.group(1) if m else None
                listing_type = ListingType.TAX_SALE if "tax" in title.lower() else ListingType.AUCTION
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=href,
                        listing_type=listing_type,
                        property_kind=PropertyKind.UNKNOWN,
                        state=state,
                        county=county,
                        description=title[:300],
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                )
        return out
