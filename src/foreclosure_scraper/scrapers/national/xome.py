"""Xome auctions — REO + foreclosure. Public search by state."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from ...apify_helper import fetch_rendered
from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

START_URLS = (
    "https://www.xome.com/auctions/state/SC",
    "https://www.xome.com/auctions/state/NC",
)
LINK_RE = re.compile(r"https?://www\.xome\.com/auctions/[A-Z]{2}/[A-Za-z\-]+/[^\s)\]\"']+", re.I)


class Xome(BaseScraper):
    slug = "national.xome"
    requires_apify = True
    name = "Xome"
    category = "national_auction"
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for u in START_URLS:
            content = await fetch_rendered(u)
            if not content:
                continue
            for href in set(LINK_RE.findall(content)):
                state = "SC" if "/SC/" in href else ("NC" if "/NC/" in href else None)
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=href.rstrip(").,]"),
                        listing_type=ListingType.AUCTION,
                        property_kind=PropertyKind.UNKNOWN,
                        state=state,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                )
        return out
