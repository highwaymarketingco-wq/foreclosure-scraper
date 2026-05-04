"""HomeHarvest — free Python library that scrapes Realtor.com (and Zillow/Redfin
via similar patterns) directly, without Apify. Replaces 4 expensive Apify
actors (zillow_bulk + trulia + realtor + foreclosure_dot_com) at $0/run.

Library: https://github.com/ZacharyHampton/HomeHarvest
Pricing: free. Uses Realtor.com's public API + stealth scraping.

For each of our 25 priority counties, we hit:
  - listing_type='for_sale' + foreclosure=True
  - past_days=30 to limit fresh listings
  - returns ~30+ fields per listing (address, price, beds, baths, sqft,
    year built, MLS#, agent, photos, foreclosure metadata)

We run these in parallel via asyncio + a thread pool (HomeHarvest is sync-only).
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...config import ALL_COUNTIES
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


def _to_listing(row, county_name: str | None = None) -> Listing | None:
    """Map a HomeHarvest DataFrame row to our Listing model."""
    url = row.get("property_url") or row.get("permalink")
    if not url:
        return None

    status_raw = (row.get("status") or "").lower()
    mls_status = (row.get("mls_status") or "").lower()

    # Map HomeHarvest statuses to our types
    if "auction" in status_raw or "auction" in mls_status:
        ltype = ListingType.AUCTION
    elif "foreclos" in status_raw or "foreclos" in mls_status:
        # FOR_SALE listings flagged foreclosure=True land here
        ltype = ListingType.FORECLOSURE_SALE
    elif "pending" in status_raw or "under_contract" in status_raw:
        return None  # skip pending — already locked in
    else:
        ltype = ListingType.FORECLOSURE_SALE  # we filtered with foreclosure=True so trust it

    style = (row.get("style") or "").lower()
    if "single" in style:
        kind = PropertyKind.SINGLE_FAMILY
    elif "condo" in style:
        kind = PropertyKind.CONDO
    elif "town" in style:
        kind = PropertyKind.TOWNHOUSE
    elif "multi" in style or "duplex" in style:
        kind = PropertyKind.MULTI_FAMILY
    elif "land" in style or "lot" in style:
        kind = PropertyKind.LAND
    elif "mobile" in style or "manufactured" in style:
        kind = PropertyKind.MOBILE
    else:
        kind = PropertyKind.UNKNOWN

    def _num(v):
        try:
            if v is None or (isinstance(v, float) and (v != v)):  # NaN check
                return None
            return float(v)
        except (TypeError, ValueError):
            return None

    photos_str = row.get("primary_photo") or ""
    photos: list[str] = []
    if photos_str and not (isinstance(photos_str, float) and photos_str != photos_str):
        photos.append(str(photos_str))
    extra_photos = row.get("alt_photos") or ""
    if isinstance(extra_photos, str) and extra_photos:
        photos.extend(extra_photos.split(", ")[:5])

    return Listing(
        source="national.homeharvest",
        source_url=str(url),
        listing_type=ltype,
        property_kind=kind,
        street_address=str(row.get("street") or "").strip() or None,
        city=str(row.get("city") or "").strip() or None,
        state=(str(row.get("state") or "").strip() or None),
        zip_code=str(row.get("zip_code") or "").strip() or None,
        county=county_name,
        opening_bid=_num(row.get("list_price")),
        market_value=_num(row.get("estimated_value")),
        tax_value=_num(row.get("assessed_value")),
        bedrooms=_num(row.get("beds")),
        bathrooms=_num(row.get("full_baths")),
        living_sqft=_num(row.get("sqft")),
        year_built=int(row["year_built"]) if row.get("year_built") and str(row["year_built"]).replace(".0", "").isdigit() else None,
        lot_size_sqft=_num(row.get("lot_sqft")),
        latitude=_num(row.get("latitude")),
        longitude=_num(row.get("longitude")),
        description=(str(row.get("text") or "") or "")[:500] or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "homeharvest": {
                "mls": row.get("mls"),
                "mls_id": row.get("mls_id"),
                "mls_status": row.get("mls_status"),
                "list_date": str(row.get("list_date") or "") or None,
                "days_on_mls": _num(row.get("days_on_mls")),
                "agent_name": row.get("agent_name"),
                "broker_name": row.get("broker_name"),
            },
            "zillow": {
                "photo": photos[0] if photos else None,
                "photos": photos[:6],
            },
        },
    )


def _scrape_one_county(seat: str, state: str, county: str) -> list[Listing]:
    """Synchronous HomeHarvest call per county-seat city. Run in thread pool."""
    try:
        from homeharvest import scrape_property
    except ImportError:
        return []
    out: list[Listing] = []
    location = f"{seat}, {state}"

    # Two passes: foreclosure-flagged for_sale (most active), then pending
    # (lis-pendens / under-contract foreclosures aren't always flagged but
    # land here). past_days=180 catches anything still listed after the auction.
    for listing_type, foreclosure in (("for_sale", True), ("pending", True)):
        try:
            df = scrape_property(
                location=location,
                listing_type=listing_type,
                foreclosure=foreclosure,
                past_days=180,
            )
            if df is None or len(df) == 0:
                continue
            for _, row in df.iterrows():
                li = _to_listing(row.to_dict(), county_name=county)
                if li:
                    out.append(li)
        except Exception as exc:
            log.debug("homeharvest.county.error", county=county, state=state,
                      type=listing_type, error=str(exc)[:100])
    return out


class HomeHarvestForeclosures(BaseScraper):
    slug = "national.homeharvest"
    name = "HomeHarvest (Realtor.com foreclosures, free direct)"
    category = "national_aggregator"
    expected_min_count = 10
    requires_apify = False
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        loop = asyncio.get_event_loop()
        out: list[Listing] = []
        # HomeHarvest's scrape_property is sync — run each county in a thread.
        # 4 parallel threads is plenty (don't hammer Realtor's servers).
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                loop.run_in_executor(pool, _scrape_one_county, c.seat, c.state, c.name)
                for c in ALL_COUNTIES
            ]
            results = await asyncio.gather(*futures, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    out.extend(r)
        # Dedupe within HomeHarvest by URL
        seen: set[str] = set()
        deduped = []
        for li in out:
            if li.source_url in seen:
                continue
            seen.add(li.source_url)
            deduped.append(li)
        return deduped
