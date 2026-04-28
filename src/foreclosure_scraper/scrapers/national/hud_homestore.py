"""HUD HomeStore — federal REO listings via the verified martc03/hud-foreclosures actor."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ...apify_helper import run_actor_sync
from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

ACTOR = "martc03/hud-foreclosures"


def _kind(raw: str | None) -> PropertyKind:
    if not raw:
        return PropertyKind.UNKNOWN
    s = raw.lower()
    if "single" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "townhouse" in s:
        return PropertyKind.TOWNHOUSE
    if "manufactured" in s or "mobile" in s:
        return PropertyKind.MOBILE
    return PropertyKind.UNKNOWN


class HudHomeStore(BaseScraper):
    slug = "national.hud_homestore"
    name = "HUD HomeStore"
    category = "national_reo"

    async def fetch(self) -> Iterable[Listing]:
        run_input = {
            "states": ["SC", "NC"],
            "propertyTypes": [
                "Single Family Home",
                "Condominium",
                "Townhouse",
                "Manufactured Housing",
            ],
            "maxRecords": 5000,
        }
        items = await run_actor_sync(ACTOR, run_input, timeout_s=300)
        out: list[Listing] = []
        for it in items:
            href = it.get("listingUrl") or it.get("url") or it.get("propertyUrl")
            if not href:
                continue
            out.append(
                Listing(
                    source=self.slug,
                    source_url=href,
                    listing_type=ListingType.REO,
                    property_kind=_kind(it.get("propertyType")),
                    street_address=it.get("address") or it.get("streetAddress"),
                    city=it.get("city"),
                    state=it.get("state"),
                    zip_code=it.get("zip") or it.get("zipCode"),
                    county=(it.get("county") or "").replace(" County", "") or None,
                    opening_bid=it.get("listPrice") or it.get("price"),
                    bedrooms=it.get("bedrooms"),
                    bathrooms=it.get("bathrooms"),
                    living_sqft=it.get("livingArea") or it.get("squareFeet"),
                    year_built=it.get("yearBuilt"),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"hud": it},
                )
            )
        return out
