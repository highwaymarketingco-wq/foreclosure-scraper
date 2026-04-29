"""LoopNet multifamily / apartment-complex listings.

Uses crawlerbros/loopnet-scraper (99% success rate, 5-star rated, $0.002/result).
This is true commercial multifamily — apartment complexes, 5+ unit buildings —
NOT the small 2-4 unit duplexes that show up on Zillow.

We hit per-state with propertyType=multifamily filter. The actor returns:
  - title, price, address, city, state, zip
  - building size (sqft), cap rate, # units (when listed)
  - broker name + contact
  - listing URL
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from ..apify_helper import run_actor_sync
from ..base_scraper import BaseScraper
from ..budget import cap
from ..models import Listing, ListingType, PropertyKind

ACTOR_ID = "memo23/loopnet-scraper-ppe"


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.]", "", str(v))
    try:
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def _parse_loopnet_item(it: dict) -> Listing | None:
    """Parse one item from memo23/loopnet-scraper-ppe.

    Probe-confirmed fields:
      propertyId, listingType, propertyType ("Multifamily"), city, state, zip,
      country, address (street only), description, listingUrl,
      images: [{url, caption, type}, ...]
    With includeListingDetails=true also yields: price, askingPrice, sqft,
    numberOfUnits, capRate, yearBuilt (in nested propertyDetails).
    """
    if not isinstance(it, dict):
        return None
    href = it.get("listingUrl") or it.get("url")
    if not href or "/Listing/" not in href:
        return None

    # Only keep multifamily property type (filter out land/retail/office/etc.)
    pt = (it.get("propertyType") or "").lower()
    if pt and "multifamily" not in pt and "apartment" not in pt:
        return None

    # Extract first photo URL from images array (replace {s} size placeholder with 'large')
    images = it.get("images") if isinstance(it.get("images"), list) else []
    photo = None
    photo_list: list[str] = []
    for img in images[:6]:
        if isinstance(img, dict) and img.get("url"):
            u = img["url"].replace("{s}", "large")
            photo_list.append(u)
            if not photo:
                photo = u

    # Detail fields when includeListingDetails=true
    details = it.get("propertyDetails") if isinstance(it.get("propertyDetails"), dict) else {}

    return Listing(
        source="multifamily.loopnet",
        source_url=href,
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.MULTI_FAMILY,
        street_address=it.get("address"),
        city=it.get("city"),
        state=(it.get("state") or "").upper()[:2] or None,
        zip_code=it.get("zip") or it.get("postalCode"),
        market_value=_num(
            it.get("price") or it.get("askingPrice") or it.get("priceNumeric")
            or details.get("price") or details.get("askingPrice")
        ),
        living_sqft=_num(
            it.get("sqft") or it.get("buildingSize") or it.get("squareFeet")
            or details.get("buildingSize") or details.get("sqft")
        ),
        year_built=int(it["yearBuilt"]) if it.get("yearBuilt") and str(it["yearBuilt"]).isdigit()
                   else (int(details["yearBuilt"]) if details.get("yearBuilt") and str(details["yearBuilt"]).isdigit() else None),
        description=(it.get("description") or "")[:500] or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "loopnet": {
                "propertyId": it.get("propertyId"),
                "propertyType": it.get("propertyType"),
                "units": it.get("numberOfUnits") or details.get("numberOfUnits") or details.get("units"),
                "cap_rate": it.get("capRate") or details.get("capRate"),
                "noi": it.get("noi") or details.get("noi"),
                "broker": it.get("broker") or it.get("agentName") or details.get("brokerName"),
            },
            "zillow": {
                # Dashboard frontend reads photos under raw.zillow.photo
                "photo": photo,
                "photos": photo_list,
            },
            "units": it.get("numberOfUnits") or details.get("numberOfUnits"),
        },
    )


class LoopNetMultifamily(BaseScraper):
    slug = "multifamily.loopnet"
    name = "LoopNet Multifamily / Apartment Complexes"
    category = "multifamily"
    expected_min_count = 3
    requires_apify = True
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        max_per_state = cap("loopnet_multifamily", default=25)
        out: list[Listing] = []
        # memo23 actor takes startUrls as [{url: "..."}] objects + has State enum.
        # Multifamily URL pattern verified working on LoopNet.
        run_input = {
            "startUrls": [
                {"url": "https://www.loopnet.com/search/multifamily-properties/south-carolina/for-sale/"},
                {"url": "https://www.loopnet.com/search/multifamily-properties/north-carolina/for-sale/"},
            ],
            "includeListingDetails": True,
            "maxItems": max_per_state,
            "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        }
        items = await run_actor_sync(
            ACTOR_ID, run_input, timeout_s=300, estimated_cost_usd=0.20
        )
        for it in items:
            li = _parse_loopnet_item(it)
            if li:
                out.append(li)
        return out
