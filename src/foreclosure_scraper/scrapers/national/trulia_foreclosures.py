"""Trulia foreclosure listings via memo23/trulia-scraper.

Trulia supports a foreclosure filter via URL: /for_sale/{city},{state}/fp_y/
Per-county URLs give us geographic granularity.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ...apify_helper import run_actor_sync
from ...base_scraper import BaseScraper
from ...budget import cap
from ...config import ALL_COUNTIES
from ...models import Listing, ListingType, PropertyKind

ACTOR = "memo23/trulia-scraper"


class TruliaForeclosures(BaseScraper):
    slug = "national.trulia"
    name = "Trulia Foreclosures"
    category = "national_aggregator"
    timeout_s = 540.0

    async def fetch(self) -> Iterable[Listing]:
        # Trulia URL pattern for foreclosures: /for_sale/<city>,<state>/fp_y/  (`fp_y` = foreclosure flag yes)
        # Use the county seat city for each of our 25 counties.
        urls = []
        for c in ALL_COUNTIES:
            seat = c.seat.replace(" ", "_")
            urls.append({"url": f"https://www.trulia.com/for_sale/{seat},{c.state}/fp_y/"})
            # Also county-level
            urls.append({"url": f"https://www.trulia.com/for_sale/{c.name.replace(' ', '_')}_County,{c.state}/fp_y/"})

        run_input = {
            "startUrls": urls,
            "maxItems": cap("trulia_foreclosures", default=750),
            "maxConcurrency": 8,
            "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        }
        items = await run_actor_sync(ACTOR, run_input, timeout_s=480)
        out: list[Listing] = []
        for it in items:
            href = it.get("url") or it.get("propertyUrl")
            if href and href.startswith("/"):
                href = f"https://www.trulia.com{href}"
            if not href:
                continue
            addr = it.get("address") if isinstance(it.get("address"), dict) else {}

            tag = (it.get("status") or it.get("listingType") or "").lower()
            ltype = ListingType.FORECLOSURE_SALE
            if "auction" in tag:
                ltype = ListingType.AUCTION
            elif "pre" in tag and "foreclos" in tag:
                ltype = ListingType.LIS_PENDENS
            elif "reo" in tag or "bank" in tag:
                ltype = ListingType.REO

            out.append(
                Listing(
                    source=self.slug,
                    source_url=href,
                    listing_type=ltype,
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=addr.get("streetAddress") or it.get("streetAddress"),
                    city=addr.get("city") or it.get("city"),
                    state=addr.get("state") or addr.get("stateCode") or it.get("state"),
                    zip_code=addr.get("zipcode") or addr.get("zip") or it.get("zip"),
                    opening_bid=it.get("price") or it.get("listPrice"),
                    bedrooms=it.get("bedrooms") or it.get("beds"),
                    bathrooms=it.get("bathrooms") or it.get("baths"),
                    living_sqft=it.get("sqft") or it.get("livingArea"),
                    year_built=it.get("yearBuilt"),
                    lot_size_sqft=it.get("lotSize"),
                    description=(it.get("description") or "")[:500] or None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"trulia": {k: it.get(k) for k in (
                        "yearBuilt", "bedrooms", "bathrooms", "sqft", "price",
                        "listingType", "status",
                    ) if k in it}},
                )
            )
        return out
