"""Realtor.com foreclosure listings via HomeHarvest (free, no Apify).

HomeHarvest scrapes Realtor.com directly via their public API.
This scraper hits state-wide queries with foreclosure=True filter to catch
listings that aren't in our priority counties but might still be relevant
(neighboring metros, large land, etc.).

Free, no Apify dependency.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# Top metros INSIDE our footprint (matched against SCOPE_DENY_COUNTIES
# downstream — out-of-scope cities like Charlotte/Raleigh/Greenville-SC
# would just get filtered, so don't bother scraping them at all).
SEARCH_LOCATIONS = (
    "Asheville, NC",
    "Hickory, NC",
    "Spartanburg, SC",
)


def _kind(style: str | None) -> PropertyKind:
    if not style:
        return PropertyKind.UNKNOWN
    s = style.lower()
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
    if "mobile" in s or "manufactured" in s:
        return PropertyKind.MOBILE
    if "commercial" in s:
        return PropertyKind.COMMERCIAL
    return PropertyKind.UNKNOWN


def _to_listing(row, slug: str) -> Listing | None:
    url = row.get("property_url") or row.get("permalink")
    if not url:
        return None
    # HomeHarvest's `foreclosure=True` is a server-side filter — every row
    # in the returned dataframe is already a foreclosure. The `status` /
    # `mls_status` fields don't always say "foreclosure" (they reflect the
    # generic MLS state: FOR_SALE / Active / Pending / Sold). Trust the
    # upstream filter; only classify the ltype using the available hints.
    status_raw = (row.get("status") or "").lower()
    mls_status = (row.get("mls_status") or "").lower()
    text_blob = (row.get("text") or "").lower()
    combined = f"{status_raw} {mls_status} {text_blob}"

    if "auction" in combined:
        ltype = ListingType.AUCTION
    elif "reo" in combined or "bank owned" in combined or "bank-owned" in combined:
        ltype = ListingType.REO
    elif "pre-foreclosure" in combined or "pre foreclosure" in combined or "lis pendens" in combined:
        ltype = ListingType.LIS_PENDENS
    else:
        ltype = ListingType.FORECLOSURE_SALE

    primary = row.get("primary_photo")
    alt = row.get("alt_photos") or ""
    photos: list[str] = []
    if primary and not (isinstance(primary, float) and primary != primary):
        photos.append(str(primary))
    if isinstance(alt, str) and alt:
        photos.extend([p.strip() for p in alt.split(",") if p.strip()][:5])

    def _f(v):
        if v in (None, "") or (isinstance(v, float) and v != v):
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    return Listing(
        source=slug,
        source_url=url,
        listing_type=ltype,
        property_kind=_kind(row.get("style") or row.get("property_type")),
        street_address=row.get("street") or row.get("full_street_line"),
        city=row.get("city"),
        state=row.get("state"),
        zip_code=str(row.get("zip_code") or "")[:5] or None,
        county=(row.get("county") or "").replace(" County", "") or None,
        opening_bid=_f(row.get("list_price")),
        bedrooms=_f(row.get("beds")),
        bathrooms=_f(row.get("full_baths")),
        living_sqft=_f(row.get("sqft")),
        year_built=int(row["year_built"]) if row.get("year_built") and str(row["year_built"]).isdigit() else None,
        latitude=_f(row.get("latitude")),
        longitude=_f(row.get("longitude")),
        description=(row.get("text") or "")[:500] or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "realtor": {
                "status": row.get("status"),
                "mls_status": row.get("mls_status"),
                "list_date": str(row.get("list_date") or ""),
                "agent": row.get("agent"),
            },
            "zillow": {
                "photo": photos[0] if photos else None,
                "photos": photos[:6],
            },
            "images": {"real": photos[:6]} if photos else {},
        },
    )


def _scrape_location(loc: str, slug: str) -> list[Listing]:
    try:
        from homeharvest import scrape_property
    except ImportError:
        return []
    out: list[Listing] = []
    seen_urls: set[str] = set()
    # Try foreclosure + auction filters
    for listing_type in ("for_sale",):
        for foreclosure in (True,):
            try:
                df = scrape_property(
                    location=loc,
                    listing_type=listing_type,
                    foreclosure=foreclosure,
                    past_days=180,
                )
            except Exception:
                continue
            if df is None or len(df) == 0:
                continue
            for _, row in df.iterrows():
                d = row.to_dict()
                li = _to_listing(d, slug)
                if li and li.source_url not in seen_urls:
                    seen_urls.add(li.source_url)
                    out.append(li)
    return out


class RealtorForeclosures(BaseScraper):
    slug = "national.realtor_foreclosures"
    name = "Realtor.com Foreclosures (HomeHarvest)"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        loop = asyncio.get_event_loop()
        out: list[Listing] = []
        seen: set[str] = set()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = await asyncio.gather(
                *(loop.run_in_executor(pool, _scrape_location, loc, self.slug)
                  for loc in SEARCH_LOCATIONS),
                return_exceptions=True,
            )
        for res in results:
            if isinstance(res, Exception):
                continue
            for li in res:
                if li.source_url not in seen:
                    seen.add(li.source_url)
                    out.append(li)
        log.info("realtor_foreclosures.done", count=len(out),
                 locations=len(SEARCH_LOCATIONS))
        return out
