"""Realtor.com foreclosure listings via the FREE dz_omar/realtor-scraper actor.

Realtor.com lets you filter foreclosures via a URL pattern. Returns full property
details (beds/baths/sqft/year built/photos/status) so we don't even need to enrich.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...apify_helper import run_actor_sync
from ...base_scraper import BaseScraper
from ...budget import cap
from ...models import Listing, ListingType, PropertyKind

ACTOR = "dz_omar/realtor-scraper"


def _kind(pt: str | None) -> PropertyKind:
    if not pt:
        return PropertyKind.UNKNOWN
    s = pt.lower()
    if "single" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "multi" in s or "duplex" in s:
        return PropertyKind.MULTI_FAMILY
    if "land" in s or "lot" in s:
        return PropertyKind.LAND
    if "commercial" in s:
        return PropertyKind.COMMERCIAL
    if "mobile" in s or "manufactured" in s:
        return PropertyKind.MOBILE
    return PropertyKind.UNKNOWN


# Realtor.com foreclosure filter URL — verified working 2026:
#   /realestateandhomes-search/<location>/show-foreclosure  (SINGULAR, no trailing 's')
# Live probe: `show-foreclosure` returns items with flags.is_foreclosure=true.
# `show-foreclosures` (plural) silently returns regular for-sale listings.
# `type-foreclosure` and `?status=foreclosure` also do not filter.
START_URLS = [
    {"url": "https://www.realtor.com/realestateandhomes-search/South-Carolina/show-foreclosure"},
    {"url": "https://www.realtor.com/realestateandhomes-search/North-Carolina/show-foreclosure"},
]


class RealtorForeclosures(BaseScraper):
    slug = "national.realtor_foreclosures"
    requires_apify = True
    expected_min_count = 30
    name = "Realtor.com Foreclosures"
    category = "national_aggregator"
    timeout_s = 540.0

    async def fetch(self) -> Iterable[Listing]:
        run_input = {
            "startUrls": START_URLS,
            "maxResults": cap("realtor_foreclosures", default=1000),
            "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        }
        items = await run_actor_sync(ACTOR, run_input, timeout_s=480)
        out: list[Listing] = []
        for it in items:
            # Probe-confirmed: items have `href`, `location` (nested w/ address), `flags`,
            # `list_price`, `description`, `last_update_date`, `details`, `estimates`.
            # Drop any that don't carry the foreclosure flag (in case the URL filter slipped).
            flags = it.get("flags") if isinstance(it.get("flags"), dict) else {}
            is_foreclosure = bool(flags.get("is_foreclosure") or flags.get("is_short_sale"))
            href = it.get("href") or it.get("url") or it.get("rdc_web_url") or it.get("propertyUrl")
            if not href:
                continue
            if href.startswith("/"):
                href = f"https://www.realtor.com{href}"
            # Skip non-foreclosures (the URL filter sometimes leaks regular listings)
            status_lower = (it.get("status") or "").lower()
            if not is_foreclosure and "foreclos" not in status_lower:
                continue

            location = it.get("location") if isinstance(it.get("location"), dict) else {}
            addr = location.get("address") if isinstance(location.get("address"), dict) else (it.get("address") or {})
            if not isinstance(addr, dict):
                addr = {}

            sale_date = None
            for k in ("auction_date", "saleDate", "auctionDate"):
                if it.get(k):
                    try:
                        sale_date = dateparser.parse(str(it[k]))
                        break
                    except (ValueError, TypeError):
                        pass

            list_price = it.get("list_price") or it.get("price")
            tag = (it.get("status") or "").lower()
            ltype = ListingType.FORECLOSURE_SALE
            if "auction" in tag:
                ltype = ListingType.AUCTION
            elif "reo" in tag or "bank" in tag:
                ltype = ListingType.REO
            elif "pre" in tag and "foreclos" in tag:
                ltype = ListingType.LIS_PENDENS

            details = it.get("details") if isinstance(it.get("details"), dict) else {}
            beds = it.get("beds") or details.get("beds")
            baths = it.get("baths") or details.get("baths") or details.get("baths_consolidated")
            sqft = it.get("sqft") or details.get("sqft") or (it.get("building_size") or {}).get("size")
            year_built = it.get("year_built") or details.get("year_built")
            lot_sqft = details.get("lot_sqft") or (it.get("lot_size") or {}).get("size")
            coords = location.get("coordinate") if isinstance(location.get("coordinate"), dict) else {}

            # description sometimes comes as a dict {text, ...}, sometimes a string
            desc_raw = it.get("description")
            if isinstance(desc_raw, dict):
                desc_raw = desc_raw.get("text") or desc_raw.get("value") or ""
            desc = (str(desc_raw) if desc_raw else "")[:500] or None

            out.append(
                Listing(
                    source=self.slug,
                    source_url=href,
                    listing_type=ltype,
                    property_kind=_kind(it.get("type") or it.get("prop_type") or details.get("type")),
                    street_address=addr.get("line") or addr.get("street") or it.get("street_address"),
                    city=addr.get("city"),
                    state=addr.get("state_code") or addr.get("state"),
                    zip_code=addr.get("postal_code") or addr.get("zip"),
                    county=(addr.get("county") or "").replace(" County", "") or None,
                    sale_date=sale_date,
                    opening_bid=list_price,
                    bedrooms=beds,
                    bathrooms=baths,
                    living_sqft=sqft,
                    year_built=year_built,
                    lot_size_sqft=lot_sqft,
                    description=desc,
                    auction_status=it.get("status"),
                    latitude=coords.get("lat"),
                    longitude=coords.get("lon"),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"realtor": {k: it.get(k) for k in (
                        "type", "year_built", "beds", "baths", "sqft", "list_price",
                        "list_date", "status", "auction_date", "tax_history",
                        "photo_count", "estimates", "flags", "open_houses",
                    ) if k in it}, "zillow": {  # dashboard reads photos under zillow key
                        "photo": (it.get("photos") or [{}])[0].get("href") if isinstance(it.get("photos"), list) and it.get("photos") else None,
                        "photos": [p.get("href") for p in (it.get("photos") or []) if isinstance(p, dict) and p.get("href")][:6],
                    }},
                )
            )
        return out
