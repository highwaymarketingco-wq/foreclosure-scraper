"""Auction.com — JS-heavy, scraped via Apify actor."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...apify_helper import run_actor_sync
from ...base_scraper import BaseScraper
from ...budget import cap
from ...models import Listing, ListingType, PropertyKind


def _kind_from(raw: str | None) -> PropertyKind:
    if not raw:
        return PropertyKind.UNKNOWN
    s = raw.lower()
    if "single" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "multi" in s or "duplex" in s or "fourplex" in s:
        return PropertyKind.MULTI_FAMILY
    if "land" in s or "lot" in s:
        return PropertyKind.LAND
    if "commercial" in s:
        return PropertyKind.COMMERCIAL
    if "manufactured" in s or "mobile" in s:
        return PropertyKind.MOBILE
    return PropertyKind.UNKNOWN


class AuctionDotCom(BaseScraper):
    slug = "national.auction_dot_com"
    name = "Auction.com"
    category = "national_auction"
    timeout_s = 360.0

    actor_candidates = ("memo23/auction-com-scraper",)

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in ("SC", "NC"):
            run_input = {
                "startUrls": [
                    f"https://www.auction.com/residential/{state}/active_lt/online,in_person,remote_bid,offer_af",
                    f"https://www.auction.com/residential/{state}/active_lt/online,in_person,remote_bid,offer_af/land_pt",
                    f"https://www.auction.com/commercial/{state}/active_lt/online,in_person,remote_bid,offer_af",
                ],
                "propertyCategory": "residential",
                "propertyState": state,
                "listingType": "active",
                "assetEventTypes": ["online", "in_person", "remote_bid", "offer"],
                "searchLimit": 500,
                "sort": "auction_date_order,resi_sort_v2",
                "nearbySearch": False,
                "requiresAggregation": False,
                "maxItems": cap("auction_dot_com", default=400) // 2,
                "maxConcurrency": 5,
                "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
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
                raw_date = it.get("saleDate") or it.get("auctionDate") or it.get("eventDate")
                if raw_date:
                    try:
                        sale_date = dateparser.parse(raw_date)
                    except (ValueError, TypeError):
                        pass
                out.append(
                    Listing(
                        source=self.slug,
                        source_url=href,
                        listing_type=ListingType.AUCTION,
                        property_kind=_kind_from(it.get("propertyType") or it.get("assetType")),
                        street_address=it.get("address") or it.get("streetAddress"),
                        city=it.get("city"),
                        state=state,
                        zip_code=it.get("zipCode") or it.get("zip"),
                        county=(it.get("county") or "").replace(" County", "") or None,
                        sale_date=sale_date,
                        opening_bid=it.get("startingBid") or it.get("openingBid") or it.get("currentBid"),
                        judgment_amount=it.get("estimatedDebt") or it.get("totalDebt"),
                        bedrooms=it.get("beds"),
                        bathrooms=it.get("baths"),
                        living_sqft=it.get("livingArea") or it.get("sqft"),
                        year_built=it.get("yearBuilt"),
                        lot_size_sqft=it.get("lotSize"),
                        auction_status=it.get("status"),
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"auction_com": {k: v for k, v in it.items() if k != "html"}},
                    )
                )
        return out
