"""Buncombe County (NC) tax foreclosure — JS-rendered map app at taxforeclosures.buncombenc.gov.

We use Apify rag-web-browser to render the page and extract listing URLs / addresses.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from ...apify_helper import fetch_rendered
from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

START_URL = "https://taxforeclosures.buncombenc.gov/"
ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
PIN_RE = re.compile(r"\bPIN[:#\s]+([0-9]{4,}-[0-9\-]{3,})", re.I)


class BuncombeTax(BaseScraper):
    slug = "counties_nc.buncombe_tax"
    name = "Buncombe County (NC) Tax Foreclosures"
    category = "county_tax"
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        content = await fetch_rendered(START_URL)
        if not content:
            return []
        out: list[Listing] = []
        seen: set[str] = set()
        for line in content.split("\n"):
            line = line.strip()
            if len(line) < 10:
                continue
            addr_m = ADDR_RE.search(line)
            pin_m = PIN_RE.search(line)
            if not (addr_m or pin_m):
                continue
            key = (addr_m.group(1) if addr_m else "") + "|" + (pin_m.group(1) if pin_m else "")
            if key in seen:
                continue
            seen.add(key)
            out.append(
                Listing(
                    source=self.slug,
                    source_url=START_URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Buncombe",
                    street_address=addr_m.group(1) if addr_m else None,
                    parcel_id=pin_m.group(1) if pin_m else None,
                    description=line[:300],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
            )
        return out
