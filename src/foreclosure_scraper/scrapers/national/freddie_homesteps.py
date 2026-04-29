"""Freddie Mac HomeSteps REO."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

API = "https://www.homesteps.com/api/property/search"


class FreddieHomeSteps(BaseScraper):
    slug = "national.freddie_homesteps"
    requires_apify = True
    name = "Freddie Mac HomeSteps"
    category = "national_reo"

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in ("SC", "NC"):
            params = {"state": state, "pagesize": 100, "page": 1}
            try:
                async with client(timeout=45.0) as c:
                    r = await c.get(API, params=params)
                    r.raise_for_status()
                    body = r.json()
            except Exception:
                continue
            for item in body.get("properties", []) or body.get("data", []) or []:
                detail_url = item.get("propertyUrl") or item.get("detailUrl")
                if not detail_url:
                    continue
                if detail_url.startswith("/"):
                    detail_url = f"https://www.homesteps.com{detail_url}"
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=detail_url,
                        listing_type=ListingType.REO,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=item.get("address") or item.get("streetAddress"),
                        city=item.get("city"),
                        state=state,
                        zip_code=item.get("zip") or item.get("zipCode"),
                        opening_bid=item.get("price") or item.get("listPrice"),
                        bedrooms=item.get("beds") or item.get("bedrooms"),
                        bathrooms=item.get("baths") or item.get("bathrooms"),
                        living_sqft=item.get("sqft"),
                        year_built=item.get("yearBuilt"),
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"homesteps": item},
                    )
                )
        return out
