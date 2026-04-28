"""Foreclosure.com — JS-heavy, scraped via Apify actor."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...apify_helper import run_actor_sync
from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind


class ForeclosureDotCom(BaseScraper):
    slug = "national.foreclosure_dot_com"
    name = "Foreclosure.com"
    category = "national_aggregator"
    timeout_s = 360.0

    actor_candidates = (
        "epctex/foreclosure-scraper",
        "tugkan/foreclosure-com-scraper",
    )

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in ("SC", "NC"):
            run_input = {
                "searchUrls": [f"https://www.foreclosure.com/listing/search/{state.lower()}"],
                "maxItems": 2000,
                "proxyConfiguration": {"useApifyProxy": True},
            }
            items: list[dict] = []
            for actor in self.actor_candidates:
                items = await run_actor_sync(actor, run_input, timeout_s=300)
                if items:
                    break
            for it in items:
                href = it.get("url") or it.get("propertyUrl")
                if not href:
                    continue
                sale_date = None
                raw_date = it.get("auctionDate") or it.get("saleDate")
                if raw_date:
                    try:
                        sale_date = dateparser.parse(raw_date)
                    except (ValueError, TypeError):
                        pass

                listing_type = ListingType.FORECLOSURE_SALE
                tag = (it.get("status") or it.get("type") or "").lower()
                if "tax" in tag:
                    listing_type = ListingType.TAX_SALE
                elif "lis pendens" in tag:
                    listing_type = ListingType.LIS_PENDENS
                elif "reo" in tag or "bank-owned" in tag:
                    listing_type = ListingType.REO

                out.append(
                    Listing(
                        source=self.slug,
                        source_url=href,
                        listing_type=listing_type,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=it.get("address"),
                        city=it.get("city"),
                        state=state,
                        zip_code=it.get("zip") or it.get("zipCode"),
                        county=(it.get("county") or "").replace(" County", "") or None,
                        sale_date=sale_date,
                        opening_bid=it.get("openingBid") or it.get("startingBid") or it.get("price"),
                        bedrooms=it.get("beds"),
                        bathrooms=it.get("baths"),
                        living_sqft=it.get("sqft"),
                        year_built=it.get("yearBuilt"),
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"foreclosure_com": it},
                    )
                )
        return out
