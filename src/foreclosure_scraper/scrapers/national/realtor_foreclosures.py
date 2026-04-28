"""Realtor.com foreclosure listings via the FREE dz_omar/realtor-scraper actor.

Realtor.com lets you filter foreclosures via a URL pattern. Returns full property
details (beds/baths/sqft/year built/photos/status) so we don't even need to enrich.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...apify_helper import run_actor_sync
from ...base_scraper import BaseScraper
from ...budget import cap
from ...models import Listing, ListingType, PropertyKind

ACTOR = "dz_omar/realtor-scraper"


def _kind(pt: str | None) -> PropertyKind:
    if not pt:
        return PropertyKind.UNKNOWN
    s = pt.lower()
    if "single" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "multi" in s or "duplex" in s:
        return PropertyKind.MULTI_FAMILY
    if "land" in s or "lot" in s:
        return PropertyKind.LAND
    if "commercial" in s:
        return PropertyKind.COMMERCIAL
    if "mobile" in s or "manufactured" in s:
        return PropertyKind.MOBILE
    return PropertyKind.UNKNOWN


# Realtor.com foreclosure-filter URL pattern: /realestateandhomes-search/<location>/show-foreclosures
START_URLS = [
    {"url": "https://www.realtor.com/realestateandhomes-search/South-Carolina/show-foreclosures"},
    {"url": "https://www.realtor.com/realestateandhomes-search/North-Carolina/show-foreclosures"},
    {"url": "https://www.realtor.com/realestateandhomes-search/South-Carolina/type-single-family-home,multi-family-home-condo,townhome,land/show-foreclosures"},
    {"url": "https://www.realtor.com/realestateandhomes-search/North-Carolina/type-single-family-home,multi-family-home-condo,townhome,land/show-foreclosures"},
]


class RealtorForeclosures(BaseScraper):
    slug = "national.realtor_foreclosures"
    name = "Realtor.com Foreclosures"
    category = "national_aggregator"
    timeout_s = 540.0

    async def fetch(self) -> Iterable[Listing]:
        run_input = {
            "startUrls": START_URLS,
            "maxResults": cap("realtor_foreclosures", default=1000),
            "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        }
        items = await run_actor_sync(ACTOR, run_input, timeout_s=480)
        out: list[Listing] = []
        for it in items:
            href = it.get("url") or it.get("rdc_web_url") or it.get("propertyUrl")
            if not href:
                continue
            addr = it.get("address") or {}
            if not isinstance(addr, dict):
                addr = {}

            sale_date = None
            for k in ("auction_date", "saleDate", "auctionDate"):
                if it.get(k):
                    try:
                        sale_date = dateparser.parse(str(it[k]))
                        break
                    except (ValueError, TypeError):
                        pass

            list_price = it.get("list_price") or it.get("price")
            tag = (it.get("status") or "").lower()
            ltype = ListingType.FORECLOSURE_SALE
            if "auction" in tag:
                ltype = ListingType.AUCTION
            elif "reo" in tag or "bank" in tag:
                ltype = ListingType.REO
            elif "pre" in tag and "foreclos" in tag:
                ltype = ListingType.LIS_PENDENS

            out.append(
                Listing(
                    source=self.slug,
                    source_url=href,
                    listing_type=ltype,
                    property_kind=_kind(it.get("type") or it.get("prop_type")),
                    street_address=addr.get("line") or it.get("street_address"),
                    city=addr.get("city"),
                    state=addr.get("state_code") or addr.get("state"),
                    zip_code=addr.get("postal_code") or addr.get("zip"),
                    county=(addr.get("county") or "").replace(" County", "") or None,
                    sale_date=sale_date,
                    opening_bid=list_price,
                    bedrooms=it.get("beds"),
                    bathrooms=it.get("baths"),
                    living_sqft=it.get("sqft") or (it.get("building_size") or {}).get("size"),
                    year_built=it.get("year_built"),
                    lot_size_sqft=(it.get("lot_size") or {}).get("size"),
                    description=(it.get("description") or "")[:500] or None,
                    auction_status=it.get("status"),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"realtor": {k: it.get(k) for k in (
                        "type", "year_built", "beds", "baths", "sqft", "list_price",
                        "list_date", "status", "auction_date", "tax_history",
                    ) if k in it}},
                )
            )
        return out
