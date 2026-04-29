"""Crexi multifamily scraper (via Apify).

Crexi is the #2 commercial RE marketplace and often surfaces inventory that
LoopNet misses (especially smaller plexes 5-20 units).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ..apify_helper import run_actor_sync
from ..base_scraper import BaseScraper
from ..budget import cap
from ..models import Listing, ListingType, PropertyKind

ACTOR_ID = "natanielsantos/crexi-scraper"

SEED_URLS = [
    "https://www.crexi.com/properties/states/SC/multifamily",
    "https://www.crexi.com/properties/states/NC/multifamily",
]


def _to_listing(item: dict) -> Listing | None:
    return Listing(
        source="multifamily.crexi",
        source_url=item.get("url") or item.get("link") or "",
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.MULTI_FAMILY,
        street_address=item.get("address") or item.get("title"),
        city=item.get("city"),
        state=(item.get("state") or "").upper()[:2] or None,
        zip_code=item.get("zip") or item.get("zipCode"),
        county=item.get("county"),
        living_sqft=float(item["sqft"]) if item.get("sqft") else None,
        year_built=int(item["yearBuilt"]) if item.get("yearBuilt") else None,
        market_value=float(item["price"]) if item.get("price") else None,
        description=item.get("description"),
        last_seen=datetime.utcnow(),
        raw={
            "units": item.get("units"),
            "cap_rate": item.get("capRate"),
            "raw": item,
        },
    )


class CrexiMultifamily(BaseScraper):
    slug = "multifamily.crexi"
    name = "Crexi (multifamily for-sale)"
    category = "multifamily"
    expected_min_count = 15
    requires_apify = True
    timeout_s = 480.0

    async def fetch(self) -> Iterable[Listing]:
        max_items = cap("crexi_multifamily", 400)
        items = await run_actor_sync(
            ACTOR_ID,
            {
                "startUrls": [{"url": u} for u in SEED_URLS],
                "maxItems": max_items,
            },
            timeout_s=360,
        )
        out: list[Listing] = []
        for it in items:
            li = _to_listing(it)
            if li and li.source_url:
                out.append(li)
        return out
