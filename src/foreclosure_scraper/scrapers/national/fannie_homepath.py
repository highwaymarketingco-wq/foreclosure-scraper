"""Fannie Mae HomePath — REO inventory from Fannie.

HomePath has a JSON search API at homepath.fanniemae.com (publicly accessible).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

API = "https://www.homepath.com/api/properties/search"


class FannieHomePath(BaseScraper):
    slug = "national.fannie_homepath"
    requires_apify = True
    name = "Fannie Mae HomePath"
    category = "national_reo"

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in ("SC", "NC"):
            payload = {
                "state": state,
                "city": "",
                "zip": "",
                "minPrice": 0,
                "maxPrice": 9999999,
                "minBeds": 0,
                "maxBeds": 99,
                "minBaths": 0,
                "maxBaths": 99,
                "page": 1,
                "pageSize": 100,
                "sort": "newest",
            }
            try:
                async with client(timeout=45.0) as c:
                    r = await c.post(API, json=payload)
                    r.raise_for_status()
                    body = r.json()
            except Exception:
                continue
            for item in body.get("properties", []) or body.get("results", []) or []:
                listing_id = item.get("listingId") or item.get("propertyId") or ""
                addr = item.get("address", {}) if isinstance(item.get("address"), dict) else {}
                street = addr.get("streetAddress") or item.get("streetAddress")
                city = addr.get("city") or item.get("city")
                zipc = addr.get("postalCode") or item.get("zipCode")
                href = item.get("detailUrl") or (
                    f"https://www.homepath.com/listing/{listing_id}" if listing_id else None
                )
                if not href:
                    continue
                kind_raw = (item.get("propertyType") or "").lower()
                kind = {
                    "single family": PropertyKind.SINGLE_FAMILY,
                    "condo": PropertyKind.CONDO,
                    "townhouse": PropertyKind.TOWNHOUSE,
                    "multi-family": PropertyKind.MULTI_FAMILY,
                    "manufactured": PropertyKind.MOBILE,
                    "land": PropertyKind.LAND,
                }.get(kind_raw, PropertyKind.UNKNOWN)

                out.append(
                    Listing(
                        source=self.slug,
                        source_url=href,
                        listing_type=ListingType.REO,
                        property_kind=kind,
                        street_address=street,
                        city=city,
                        state=state,
                        zip_code=zipc,
                        opening_bid=item.get("listPrice") or item.get("price"),
                        bedrooms=item.get("bedrooms"),
                        bathrooms=item.get("bathrooms"),
                        living_sqft=item.get("livingArea") or item.get("squareFeet"),
                        year_built=item.get("yearBuilt"),
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"homepath": item},
                    )
                )
        return out
