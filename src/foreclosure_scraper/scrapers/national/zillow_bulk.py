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
    requires_apify = True
    expected_min_count = 50
    name = "Zillow Bulk Foreclosure Search"
    category = "national_aggregator"
    timeout_s = 720.0

    async def fetch(self) -> Iterable[Listing]:
        # The actor expects "City ST" format (no "County", no comma between city and state).
        # Live probe confirmed: "Greenville County, SC" -> 0 results, "Greenville SC" -> 14 results.
        # We hit each county SEAT (the largest city in the county) which gives the actor's
        # location resolver something it can geocode. The dedupe + scope filter trims to our 25-county footprint.
        locations = [f"{c.seat} {c.state}" for c in ALL_COUNTIES]
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
        for wrapped in items:
            # Probe-confirmed shape: {rawData: {property: {...}, resultType: ...}, scrapedAt, location}
            # The real Zillow payload lives at wrapped.rawData.property
            if not isinstance(wrapped, dict):
                continue
            raw = wrapped.get("rawData") if isinstance(wrapped.get("rawData"), dict) else wrapped
            it = raw.get("property") if isinstance(raw.get("property"), dict) else raw
            if not isinstance(it, dict):
                continue
            href = it.get("hdpUrl") or it.get("detailUrl") or it.get("url")
            if href and href.startswith("/"):
                href = f"https://www.zillow.com{href}"
            if not href and it.get("zpid"):
                href = f"https://www.zillow.com/homedetails/{it['zpid']}_zpid/"
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

            # price/zestimate/taxAssessedValue can be nested {value, pricePerSquareFoot}
            def _num(v):
                if isinstance(v, dict):
                    v = v.get("value")
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

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
                    opening_bid=_num(it.get("price") or it.get("listPrice")),
                    market_value=_num(it.get("zestimate")),
                    tax_value=_num(it.get("taxAssessedValue")),
                    bedrooms=it.get("bedrooms") or it.get("beds"),
                    bathrooms=it.get("bathrooms") or it.get("baths"),
                    living_sqft=_num(it.get("livingArea") or it.get("livingAreaValue")),
                    year_built=it.get("yearBuilt"),
                    lot_size_sqft=_num(it.get("lotSize") or it.get("lotAreaValue")),
                    description=(str(it.get("description")) if it.get("description") else "")[:500] or None,
                    latitude=it.get("latitude"),
                    longitude=it.get("longitude"),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"zillow_bulk": {k: it.get(k) for k in (
                        "zpid", "homeType", "homeStatus", "yearBuilt", "bedrooms", "bathrooms",
                        "livingArea", "lotSize", "zestimate", "taxAssessedValue",
                    ) if k in it}, "zillow": {
                        # Front-end dashboard reads raw.zillow.photo first
                        "photo": (
                            (it.get("media") or {}).get("propertyPhotoLinks", {}).get("highResolutionLink")
                            or (it.get("media") or {}).get("thirdPartyPhotoLinks", {}).get("streetViewLink")
                        ),
                        "photos": [
                            (it.get("media") or {}).get("propertyPhotoLinks", {}).get("highResolutionLink"),
                        ] if it.get("media") else [],
                        "zpid": it.get("zpid"),
                        "homeType": it.get("homeType"),
                        "zestimate": it.get("zestimate"),
                        "yearBuilt": it.get("yearBuilt"),
                        "bedrooms": it.get("bedrooms"),
                        "bathrooms": it.get("bathrooms"),
                        "livingArea": it.get("livingArea"),
                    }},
                )
            )
        return out
