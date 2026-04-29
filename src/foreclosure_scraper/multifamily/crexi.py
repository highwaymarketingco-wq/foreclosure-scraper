"""Crexi multifamily / apartment-complex listings.

Uses shahidirfan/crexi-property-scraper (99.5% success, $0.001/result).
Crexi is the #2 commercial RE marketplace and often has inventory LoopNet
misses, especially smaller plexes (5-20 units).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from ..apify_helper import run_actor_sync
from ..base_scraper import BaseScraper
from ..budget import cap
from ..models import Listing, ListingType, PropertyKind

ACTOR_ID = "shahidirfan/crexi-property-scraper"

# Crexi search URLs by state — multifamily property type filter.
# Crexi exposes ?propertyTypes=Multifamily as a query parameter.
SEARCH_URLS = {
    "SC": "https://www.crexi.com/properties?propertyTypes=Multifamily&states=SC&pageSize=60",
    "NC": "https://www.crexi.com/properties?propertyTypes=Multifamily&states=NC&pageSize=60",
}


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.]", "", str(v))
    try:
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def _parse_crexi_item(it: dict) -> Listing | None:
    if not isinstance(it, dict):
        return None
    href = it.get("url") or it.get("link") or it.get("href")
    if not href:
        return None
    if href.startswith("/"):
        href = f"https://www.crexi.com{href}"

    addr = it.get("address") or {}
    if isinstance(addr, str):
        addr_str = addr
        addr = {}
    else:
        addr_str = ""

    return Listing(
        source="multifamily.crexi",
        source_url=href,
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.MULTI_FAMILY,
        street_address=addr.get("street") or addr.get("line1") or addr_str or it.get("title"),
        city=addr.get("city") or it.get("city"),
        state=(addr.get("state") or it.get("state") or "").upper()[:2] or None,
        zip_code=addr.get("zip") or addr.get("zipCode") or addr.get("postalCode"),
        market_value=_num(it.get("price") or it.get("askingPrice")),
        living_sqft=_num(it.get("buildingSize") or it.get("sqft") or it.get("squareFeet")),
        year_built=int(it["yearBuilt"]) if it.get("yearBuilt") and str(it["yearBuilt"]).isdigit() else None,
        description=(str(it.get("description") or it.get("summary") or it.get("title") or ""))[:500] or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "crexi": {
                "title": it.get("title") or it.get("name"),
                "units": it.get("units") or it.get("numberOfUnits"),
                "cap_rate": it.get("capRate") or it.get("cap_rate"),
                "noi": it.get("noi"),
                "broker": it.get("broker") or it.get("brokerName"),
                "image": it.get("image") or it.get("imageUrl") or it.get("photo"),
            },
            "zillow": {
                # Surface photo on dashboard (same key the frontend reads)
                "photo": it.get("image") or it.get("imageUrl") or it.get("photo"),
                "photos": [it.get("image") or it.get("imageUrl") or it.get("photo")]
                          if (it.get("image") or it.get("imageUrl") or it.get("photo")) else [],
            },
        },
    )


class CrexiMultifamily(BaseScraper):
    slug = "multifamily.crexi"
    name = "Crexi Multifamily / Apartment Complexes"
    category = "multifamily"
    expected_min_count = 3
    requires_apify = True
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        max_per_state = cap("crexi_multifamily", default=25)
        out: list[Listing] = []
        for st, url in SEARCH_URLS.items():
            run_input = {
                "startUrl": url,
                "results_wanted": max_per_state,
                "max_pages": 2,
                "proxyConfiguration": {"useApifyProxy": False},
            }
            items = await run_actor_sync(
                ACTOR_ID, run_input, timeout_s=180, estimated_cost_usd=0.10
            )
            for it in items:
                li = _parse_crexi_item(it)
                if li:
                    # If Crexi didn't return state, infer from search URL
                    if not li.state:
                        li.state = st
                    out.append(li)
        return out
