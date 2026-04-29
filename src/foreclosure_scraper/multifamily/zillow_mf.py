"""Multifamily for-sale via Zillow (clearpath/zillow-bulk-search-unlimited-scraper).

This is the SAME actor we already use successfully for foreclosures, just with
homeTypes filtered to multi-family + apartment. We've verified its input shape
and parser end-to-end. Cost: ~$0.003 per result.

We target only the 6 priority counties (Spartanburg SC + Cherokee SC + Rutherford
/ Cleveland / Henderson / Polk NC) keyed by their county-seat city — the format
the actor's location resolver actually accepts (city + ST, no comma, no "County").
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ..apify_helper import run_actor_sync
from ..base_scraper import BaseScraper
from ..budget import cap
from ..config import in_scope
from ..models import Listing, ListingType, PropertyKind

ACTOR_ID = "clearpath/zillow-bulk-search-unlimited-scraper"

# Priority counties only — keyed by county-seat city (the actor's resolver expects
# "Greenville SC" format, not "Greenville County, SC").
PRIORITY_LOCATIONS: tuple[tuple[str, str, str], ...] = (
    # (city, state, county for in-scope check)
    ("Spartanburg", "SC", "Spartanburg"),
    ("Gaffney", "SC", "Cherokee"),
    ("Rutherfordton", "NC", "Rutherford"),
    ("Shelby", "NC", "Cleveland"),
    ("Hendersonville", "NC", "Henderson"),
    ("Columbus", "NC", "Polk"),
)


def _num(v):
    """Zillow returns nested {value, pricePerSquareFoot} for price/zestimate."""
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


class ZillowMultifamily(BaseScraper):
    slug = "multifamily.zillow"
    name = "Zillow Multifamily (for-sale)"
    category = "multifamily"
    expected_min_count = 5
    requires_apify = True
    timeout_s = 480.0

    async def fetch(self) -> Iterable[Listing]:
        locations = [f"{seat} {state}" for seat, state, _ in PRIORITY_LOCATIONS]
        run_input = {
            "locations": locations,
            "propertyType": "forSale",
            "homeTypes": ["multiFamily", "apartment"],
            "maxResultsPerLocation": cap("zillow_multifamily", default=80),
            "includePendingAndUnderContract": False,
        }
        # Estimated cost: 6 locations x 80 results x $0.003 = ~$1.44, plus $0.0005 start
        items = await run_actor_sync(
            ACTOR_ID, run_input, timeout_s=400, estimated_cost_usd=2.0
        )
        out: list[Listing] = []
        county_lookup = {(seat, state): county for seat, state, county in PRIORITY_LOCATIONS}

        for wrapped in items:
            # Probe-confirmed shape: {rawData: {property: {...}}, scrapedAt, location}
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
            city = addr.get("city") or it.get("city")
            state = addr.get("state") or it.get("state")
            zip_code = addr.get("zipcode") or it.get("zipcode")

            # Map city -> county based on priority list
            county = None
            for seat, st, c in PRIORITY_LOCATIONS:
                if (city or "").lower() == seat.lower() and (state or "").upper() == st:
                    county = c
                    break

            # Pull photo from media field (we already wired this for foreclosure)
            media = it.get("media") if isinstance(it.get("media"), dict) else {}
            photo = (
                (media.get("propertyPhotoLinks") or {}).get("highResolutionLink")
                or (media.get("thirdPartyPhotoLinks") or {}).get("streetViewLink")
            )

            out.append(
                Listing(
                    source=self.slug,
                    source_url=href,
                    listing_type=ListingType.UNKNOWN,
                    property_kind=PropertyKind.MULTI_FAMILY,
                    street_address=addr.get("streetAddress") or it.get("streetAddress"),
                    city=city,
                    state=state,
                    zip_code=zip_code,
                    county=county,
                    market_value=_num(it.get("price") or it.get("listPrice")),
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
                    raw={
                        "zillow": {
                            "photo": photo,
                            "photos": [photo] if photo else [],
                            "zpid": it.get("zpid"),
                            "homeType": it.get("homeType"),
                            "zestimate": _num(it.get("zestimate")),
                            "yearBuilt": it.get("yearBuilt"),
                            "bedrooms": it.get("bedrooms"),
                            "bathrooms": it.get("bathrooms"),
                            "livingArea": _num(it.get("livingArea")),
                        },
                        "units": it.get("units"),  # may not always populate from Zillow
                    },
                )
            )
        return out
