"""Zillow foreclosure / pre-foreclosure listings via Apify."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ...apify_helper import run_actor_sync
from ...base_scraper import BaseScraper
from ...budget import cap
from ...models import Listing, ListingType, PropertyKind

# Zillow blocks IPs aggressively, Apify handles proxy rotation.
ACTOR_CANDIDATES = (
    "maxcopell/zillow-detail-scraper",
    "epctex/zillow-search-scraper",
    "petr_cermak/zillow-scraper",
)


class ZillowForeclosures(BaseScraper):
    slug = "national.zillow_foreclosures"
    name = "Zillow Foreclosures"
    category = "national_aggregator"
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        # Zillow URL format for foreclosures is /<state-or-region>/foreclosures/
        urls = [
            "https://www.zillow.com/sc/foreclosures/",
            "https://www.zillow.com/nc/foreclosures/",
            "https://www.zillow.com/sc/auction_lt/",
            "https://www.zillow.com/nc/auction_lt/",
            "https://www.zillow.com/sc/pre-foreclosure_lt/",
            "https://www.zillow.com/nc/pre-foreclosure_lt/",
        ]
        run_input = {
            "searchUrls": [{"url": u} for u in urls],
            "extractionMethod": "PAGINATION",
            "maxItems": cap("zillow_foreclosures", default=300),
            "proxyConfiguration": {"useApifyProxy": True},
        }
        items: list[dict] = []
        for actor in ACTOR_CANDIDATES:
            items = await run_actor_sync(actor, run_input, timeout_s=300)
            if items:
                break

        for it in items:
            href = it.get("hdpUrl") or it.get("detailUrl") or it.get("url")
            if href and href.startswith("/"):
                href = f"https://www.zillow.com{href}"
            if not href:
                continue
            addr = it.get("address", {}) if isinstance(it.get("address"), dict) else {}
            kind_raw = (it.get("homeType") or "").upper()
            kind = {
                "SINGLE_FAMILY": PropertyKind.SINGLE_FAMILY,
                "CONDO": PropertyKind.CONDO,
                "TOWNHOUSE": PropertyKind.TOWNHOUSE,
                "MULTI_FAMILY": PropertyKind.MULTI_FAMILY,
                "MANUFACTURED": PropertyKind.MOBILE,
                "LOT": PropertyKind.LAND,
                "VACANT_LAND": PropertyKind.LAND,
            }.get(kind_raw, PropertyKind.UNKNOWN)
            tag = (it.get("homeStatus") or it.get("status") or "").lower()
            listing_type = ListingType.FORECLOSURE_SALE
            if "auction" in tag:
                listing_type = ListingType.AUCTION
            elif "pre" in tag and "foreclosure" in tag:
                listing_type = ListingType.LIS_PENDENS
            elif "reo" in tag or "bank" in tag:
                listing_type = ListingType.REO

            out.append(
                Listing(
                    source=self.slug,
                    source_url=href,
                    listing_type=listing_type,
                    property_kind=kind,
                    street_address=addr.get("streetAddress") or it.get("streetAddress"),
                    city=addr.get("city") or it.get("city"),
                    state=addr.get("state") or it.get("state"),
                    zip_code=addr.get("zipcode") or it.get("zipcode"),
                    opening_bid=it.get("price") or it.get("priceHistory", [{}])[0].get("price"),
                    bedrooms=it.get("bedrooms"),
                    bathrooms=it.get("bathrooms"),
                    living_sqft=it.get("livingArea"),
                    year_built=it.get("yearBuilt"),
                    lot_size_sqft=it.get("lotSize"),
                    description=(it.get("description") or "")[:500] or None,
                    latitude=it.get("latitude"),
                    longitude=it.get("longitude"),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"zillow": {k: v for k, v in it.items() if k not in ("photos", "responsivePhotos")}},
                )
            )
        return out
