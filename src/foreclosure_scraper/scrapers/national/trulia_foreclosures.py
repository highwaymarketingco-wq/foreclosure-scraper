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
    requires_apify = True
    expected_min_count = 30
    name = "Trulia Foreclosures"
    category = "national_aggregator"
    timeout_s = 540.0

    async def fetch(self) -> Iterable[Listing]:
        # Trulia URL pattern for foreclosures: /for_sale/<city>,<state>/fp_y/
        # Probe-confirmed: 50-URL batches trigger 408 timeouts. Cap at 12 county seats
        # only (drop the county-level URLs which Trulia rarely indexes anyway).
        # The 12 seats below cover the largest population centers in our 25-county footprint.
        # Trulia 408s aggressively when given >5 URLs in one batch. We keep this small.
        # The 4 hubs below cover all major upstate SC + western NC markets; smaller cities
        # rarely have foreclosure inventory on Trulia anyway (most go to auction.com).
        urls = [
            {"url": "https://www.trulia.com/for_sale/Greenville,SC/fp_y/"},
            {"url": "https://www.trulia.com/for_sale/Spartanburg,SC/fp_y/"},
            {"url": "https://www.trulia.com/for_sale/Charlotte,NC/fp_y/"},
            {"url": "https://www.trulia.com/for_sale/Asheville,NC/fp_y/"},
        ]

        run_input = {
            "startUrls": urls,
            "maxItems": cap("trulia_foreclosures", default=200),
            "maxConcurrency": 2,
            "maxRequestRetries": 8,
            "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        }
        items = await run_actor_sync(ACTOR, run_input, timeout_s=540)
        out: list[Listing] = []
        for it in items:
            # Probe-confirmed: url is relative `/home/...`, status is `currentStatus`,
            # address is nested, price is string `"$329,900"`, sqft under `floorSpace.value`.
            href = it.get("url") or it.get("originalUrl") or it.get("propertyUrl")
            if href and href.startswith("/"):
                href = f"https://www.trulia.com{href}"
            if not href:
                continue
            addr = it.get("address") if isinstance(it.get("address"), dict) else {}

            # currentStatus / status can be either a dict {type, label} or a plain string
            def _flatten_status(v):
                if isinstance(v, dict):
                    return " ".join(str(x) for x in (v.get("label"), v.get("type"), v.get("text")) if x)
                return str(v) if v else ""
            tag = " ".join(_flatten_status(it.get(k)) for k in ("currentStatus", "status", "listingType")).lower()
            ltype = ListingType.FORECLOSURE_SALE
            if "auction" in tag:
                ltype = ListingType.AUCTION
            elif "pre" in tag and "foreclos" in tag:
                ltype = ListingType.LIS_PENDENS
            elif "reo" in tag or "bank" in tag:
                ltype = ListingType.REO

            # Price comes as "$329,900" string; strip non-numeric
            price_raw = it.get("price") or it.get("listPrice")
            price = None
            if price_raw:
                try:
                    price = float(str(price_raw).replace("$", "").replace(",", "").split()[0])
                except (ValueError, IndexError):
                    pass

            floor = it.get("floorSpace") if isinstance(it.get("floorSpace"), dict) else {}
            sqft = floor.get("value") or it.get("sqft") or it.get("livingArea")
            try:
                sqft = float(sqft) if sqft else None
            except (TypeError, ValueError):
                sqft = None

            coords = it.get("coordinates") if isinstance(it.get("coordinates"), dict) else {}

            # bedrooms/bathrooms come as strings like "3 Beds", "2.5 Baths"
            def _parse_num(v):
                if v is None:
                    return None
                if isinstance(v, (int, float)):
                    return float(v)
                # extract first number from a string
                import re
                m = re.search(r"[\d.]+", str(v))
                return float(m.group(0)) if m else None

            beds = _parse_num(it.get("bedrooms") or it.get("beds"))
            baths = _parse_num(it.get("bathrooms") or it.get("baths"))

            out.append(
                Listing(
                    source=self.slug,
                    source_url=href,
                    listing_type=ltype,
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=addr.get("streetAddress") or it.get("streetAddress"),
                    city=addr.get("city") or it.get("city"),
                    state=addr.get("state") or addr.get("stateCode") or it.get("state"),
                    zip_code=addr.get("zipCode") or addr.get("zipcode") or addr.get("zip") or it.get("zip"),
                    opening_bid=price,
                    bedrooms=beds,
                    bathrooms=baths,
                    living_sqft=sqft,
                    year_built=it.get("yearBuilt"),
                    description=(it.get("description") or "")[:500] or None,
                    latitude=coords.get("latitude") or coords.get("lat"),
                    longitude=coords.get("longitude") or coords.get("lng"),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"trulia": {k: it.get(k) for k in (
                        "yearBuilt", "bedrooms", "bathrooms", "price", "currentStatus",
                        "foreclosureInfo", "legacyId", "neighborhood", "formattedLocation",
                    ) if k in it}},
                )
            )
        return out
