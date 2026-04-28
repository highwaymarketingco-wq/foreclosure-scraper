"""Aldridge Pite — sale-day listings sit behind an 'I agree' click-through.

We use Apify rag-web-browser to render the post-disclaimer page for each state.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from ...apify_helper import fetch_rendered
from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

URLS = (
    ("https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-nc/", "NC"),
    ("https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-sc/", "SC"),
)
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
COUNTY_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)\s+County\b")


class AldridgePite(BaseScraper):
    slug = "law_firms.aldridge_pite"
    name = "Aldridge Pite"
    category = "law_firm"
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for url, state in URLS:
            content = await fetch_rendered(url)
            if not content:
                continue
            for line in content.split("\n"):
                addr_m = ADDR_RE.search(line)
                if not addr_m:
                    continue
                county_m = COUNTY_RE.search(line)
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=url,
                        listing_type=ListingType.FORECLOSURE_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=addr_m.group(1),
                        state=state,
                        county=county_m.group(1) if county_m else None,
                        description=line[:300],
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                    )
                )
        return out
