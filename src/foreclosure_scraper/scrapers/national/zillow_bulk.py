"""Zillow bulk foreclosure search via clearpath/zillow-bulk-search-unlimited-scraper.

Bypasses Zillow's 1000-result cap. We pass each county as a 'location' string
and filter by foreclosure listing types (auction / foreclosure / preforeclosure).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ...apify_helper import run_actor_sync
from ...base_scraper import BaseScraper
from ...budget import cap
from ...config import ALL_COUNTIES
from ...models import Listing, ListingType, PropertyKind

ACTOR = "clearpath/zillow-bulk-search-unlimited-scraper"


def _kind(home_type: str | None) -> PropertyKind:
    if not home_type:
        return PropertyKind.UNKNOWN
    s = home_type.lower()
    return {
        "single_family": PropertyKind.SINGLE_FAMILY,
        "single family": PropertyKind.SINGLE_FAMILY,
        "condo": PropertyKind.CONDO,
        "condo/co-op": PropertyKind.CONDO,
        "townhouse": PropertyKind.TOWNHOUSE,
        "townhome": PropertyKind.TOWNHOUSE,
        "multi_family": PropertyKind.MULTI_FAMILY,
        "multi-family": PropertyKind.MULTI_FAMILY,
        "manufactured": PropertyKind.MOBILE,
        "land": PropertyKind.LAND,
        "lot": PropertyKind.LAND,
        "vacant_land": PropertyKind.LAND,
    }.get(s, PropertyKind.UNKNOWN)


class ZillowBulkForeclosures(BaseScraper):
    slug = "national.zillow_bulk"
    name = "Zillow Bulk Foreclosure Search"
    category = "national_aggregator"
    timeout_s = 720.0

    async def fetch(self) -> Iterable[Listing]:
        # One search per county for granular geographic coverage
        locations = [f"{c.name} County, {c.state}" for c in ALL_COUNTIES]
        run_input = {
            "locations": locations,
            "propertyType": "forSale",
            "homeTypes": ["singleFamily", "condo", "townhome", "multiFamily", "manufactured", "land"],
            "listingTypes": ["auction", "foreclosure", "foreclosed", "preforeclosure"],
            "maxResultsPerLocation": cap("zillow_bulk_foreclosures", default=80),
            "includePendingAndUnderContract": False,
        }
        items = await run_actor_sync(ACTOR, run_input, timeout_s=600)
        out: list[Listing] = []
        for it in items:
            href = it.get("hdpUrl") or it.get("detailUrl") or it.get("url")
            if href and href.startswith("/"):
                href = f"https://www.zillow.com{href}"
            if not href:
                continue

            addr = it.get("address") if isinstance(it.get("address"), dict) else {}

            tag = (it.get("homeStatus") or it.get("listingStatus") or "").lower()
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
                    property_kind=_kind(it.get("homeType") or it.get("propertyType")),
                    street_address=addr.get("streetAddress") or it.get("streetAddress"),
                    city=addr.get("city") or it.get("city"),
                    state=addr.get("state") or it.get("state"),
                    zip_code=addr.get("zipcode") or it.get("zipcode"),
                    opening_bid=it.get("price") or it.get("listPrice"),
                    market_value=it.get("zestimate"),
                    tax_value=it.get("taxAssessedValue"),
                    bedrooms=it.get("bedrooms") or it.get("beds"),
                    bathrooms=it.get("bathrooms") or it.get("baths"),
                    living_sqft=it.get("livingArea") or it.get("livingAreaValue"),
                    year_built=it.get("yearBuilt"),
                    lot_size_sqft=it.get("lotSize") or it.get("lotAreaValue"),
                    description=(it.get("description") or "")[:500] or None,
                    latitude=it.get("latitude"),
                    longitude=it.get("longitude"),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"zillow_bulk": {k: it.get(k) for k in (
                        "zpid", "homeType", "homeStatus", "yearBuilt", "bedrooms", "bathrooms",
                        "livingArea", "lotSize", "zestimate", "taxAssessedValue",
                    ) if k in it}},
                )
            )
        return out
