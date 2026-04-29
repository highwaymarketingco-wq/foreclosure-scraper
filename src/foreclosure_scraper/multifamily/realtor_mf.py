"""Realtor.com multifamily scraper (free Apify actor).

Realtor.com indexes multi-family residential up to 4 units (which Zillow
classifies as residential) plus 5+ unit commercial. This is the FREE actor
in our stack, so we crank it up.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ..apify_helper import run_actor_sync
from ..base_scraper import BaseScraper
from ..budget import cap
from ..models import Listing, ListingType, PropertyKind

ACTOR_ID = "tugkan/realtor-scraper"

SEED_URLS = [
    # multi-family residential (2-4 units) per state
    "https://www.realtor.com/realestateandhomes-search/South-Carolina/type-multi-family-home",
    "https://www.realtor.com/realestateandhomes-search/North-Carolina/type-multi-family-home",
]


def _to_listing(item: dict) -> Listing | None:
    addr = item.get("address") or {}
    return Listing(
        source="multifamily.realtor",
        source_url=item.get("url") or item.get("permalink") or "",
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.MULTI_FAMILY,
        street_address=addr.get("line"),
        city=addr.get("city"),
        state=(addr.get("state_code") or "").upper() or None,
        zip_code=addr.get("postal_code"),
        county=addr.get("county"),
        living_sqft=float(item["sqft"]) if item.get("sqft") else None,
        year_built=int(item["year_built"]) if item.get("year_built") else None,
        market_value=float(item["price"]) if item.get("price") else None,
        bedrooms=item.get("beds"),
        bathrooms=item.get("baths"),
        latitude=(addr.get("coordinate") or {}).get("lat"),
        longitude=(addr.get("coordinate") or {}).get("lon"),
        last_seen=datetime.utcnow(),
        raw={"raw": item},
    )


class RealtorMultifamily(BaseScraper):
    slug = "multifamily.realtor"
    name = "Realtor.com (multi-family)"
    category = "multifamily"
    expected_min_count = 25
    requires_apify = True
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        max_items = cap("realtor_multifamily", 600)
        items = await run_actor_sync(
            ACTOR_ID,
            {
                "startUrls": [{"url": u} for u in SEED_URLS],
                "maxItems": max_items,
            },
            timeout_s=300,
        )
        out: list[Listing] = []
        for it in items:
            li = _to_listing(it)
            if li and li.source_url:
                out.append(li)
        return out
