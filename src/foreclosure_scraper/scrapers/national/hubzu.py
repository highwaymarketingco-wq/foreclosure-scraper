"""Hubzu — auction REO. JS-heavy, fetched via Apify rag-web-browser fallback."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from ...apify_helper import fetch_rendered
from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

START_URLS = (
    "https://www.hubzu.com/properties?location=south%20carolina",
    "https://www.hubzu.com/properties?location=north%20carolina",
)

LINK_RE = re.compile(r"https?://www\.hubzu\.com/(?:property|home)/[^\s)\]\"']+", re.I)


class Hubzu(BaseScraper):
    slug = "national.hubzu"
    requires_apify = True
    name = "Hubzu"
    category = "national_auction"
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for u in START_URLS:
            content = await fetch_rendered(u)
            if not content:
                continue
            seen: set[str] = set()
            for href in LINK_RE.findall(content):
                href = href.rstrip(").,]")
                if href in seen:
                    continue
                seen.add(href)
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=href,
                        listing_type=ListingType.AUCTION,
                        property_kind=PropertyKind.UNKNOWN,
                        state="SC" if "south%20carolina" in u else "NC",
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                )
        return out
