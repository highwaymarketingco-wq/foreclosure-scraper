"""LoopNet multifamily scraper (via Apify).

Searches LoopNet's for-sale multifamily inventory in our footprint. LoopNet is
the dominant US commercial RE marketplace - apartments, complexes, mixed-use.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ..apify_helper import run_actor_sync
from ..base_scraper import BaseScraper
from ..budget import cap
from ..config import in_scope
from ..models import Listing, ListingType, PropertyKind

ACTOR_ID = "epctex/loopnet-scraper"

# LoopNet city pages we'll seed (one per major market in scope; the actor
# auto-paginates inside each city)
SEED_URLS = [
    # SC upstate
    "https://www.loopnet.com/search/multifamily-properties/greenville-sc/for-sale/",
    "https://www.loopnet.com/search/multifamily-properties/spartanburg-sc/for-sale/",
    "https://www.loopnet.com/search/multifamily-properties/anderson-sc/for-sale/",
    "https://www.loopnet.com/search/multifamily-properties/greenwood-sc/for-sale/",
    # NC nearby
    "https://www.loopnet.com/search/multifamily-properties/asheville-nc/for-sale/",
    "https://www.loopnet.com/search/multifamily-properties/charlotte-nc/for-sale/",
    "https://www.loopnet.com/search/multifamily-properties/hendersonville-nc/for-sale/",
    "https://www.loopnet.com/search/multifamily-properties/gastonia-nc/for-sale/",
    "https://www.loopnet.com/search/multifamily-properties/shelby-nc/for-sale/",
    "https://www.loopnet.com/search/multifamily-properties/forest-city-nc/for-sale/",
]


def _to_listing(item: dict) -> Listing | None:
    address = item.get("address") or item.get("title") or ""
    state = (item.get("state") or "").upper()[:2]
    county = item.get("county") or ""
    if state and county and not in_scope(county, state):
        # LoopNet doesn't always provide county - keep going if we don't have it
        pass

    sf = item.get("buildingSize") or item.get("squareFeet")
    units = item.get("units") or item.get("unitCount")
    price = item.get("price") or item.get("askingPrice")
    cap_rate = item.get("capRate")
    yr = item.get("yearBuilt")

    return Listing(
        source="multifamily.loopnet",
        source_url=item.get("url") or item.get("detailUrl") or "",
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.MULTI_FAMILY,
        street_address=address,
        city=item.get("city"),
        state=state or None,
        zip_code=item.get("zipCode") or item.get("postalCode"),
        county=county or None,
        living_sqft=float(sf) if sf else None,
        year_built=int(yr) if yr else None,
        market_value=float(price) if price else None,
        description=item.get("description"),
        last_seen=datetime.utcnow(),
        raw={
            "units": units,
            "cap_rate": cap_rate,
            "noi": item.get("noi"),
            "gross_income": item.get("grossIncome"),
            "expenses": item.get("operatingExpenses"),
            "raw": item,
        },
    )


class LoopNetMultifamily(BaseScraper):
    slug = "multifamily.loopnet"
    name = "LoopNet (multifamily for-sale)"
    category = "multifamily"
    expected_min_count = 30
    requires_apify = True
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        max_items = cap("loopnet_multifamily", 600)
        items = await run_actor_sync(
            ACTOR_ID,
            {
                "startUrls": [{"url": u} for u in SEED_URLS],
                "maxItems": max_items,
                "extendOutputFunction": "($) => ({})",
            },
            timeout_s=480,
        )
        out: list[Listing] = []
        for it in items:
            li = _to_listing(it)
            if li and li.source_url:
                out.append(li)
        return out
