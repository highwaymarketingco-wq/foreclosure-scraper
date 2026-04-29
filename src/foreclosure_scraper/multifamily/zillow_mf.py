"""Zillow multifamily (5+ units) scraper.

Zillow has a multi-family residential filter we can hit per county. Use the
generic Zillow search actor with the multi-family filter on (Zillow's URL
structure: /homes/<county>-<state>/multi-family_type/).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ..apify_helper import run_actor_sync
from ..base_scraper import BaseScraper
from ..budget import cap
from ..config import in_scope
from ..models import Listing, ListingType, PropertyKind

ACTOR_ID = "maxcopell/zillow-scraper"

# Counties in scope (county-state slugs)
COUNTY_SLUGS = [
    # SC
    ("Greenville-County-SC", "SC", "Greenville"),
    ("Spartanburg-County-SC", "SC", "Spartanburg"),
    ("Anderson-County-SC", "SC", "Anderson"),
    ("Pickens-County-SC", "SC", "Pickens"),
    ("Oconee-County-SC", "SC", "Oconee"),
    ("Greenwood-County-SC", "SC", "Greenwood"),
    ("Cherokee-County-SC", "SC", "Cherokee"),
    # NC
    ("Buncombe-County-NC", "NC", "Buncombe"),
    ("Mecklenburg-County-NC", "NC", "Mecklenburg"),
    ("Henderson-County-NC", "NC", "Henderson"),
    ("Gaston-County-NC", "NC", "Gaston"),
    ("Rutherford-County-NC", "NC", "Rutherford"),
    ("Cleveland-County-NC", "NC", "Cleveland"),
    ("Burke-County-NC", "NC", "Burke"),
]


def _to_listing(item: dict, state: str, county: str) -> Listing | None:
    return Listing(
        source="multifamily.zillow",
        source_url=item.get("detailUrl") or item.get("url") or "",
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.MULTI_FAMILY,
        street_address=item.get("address") or item.get("streetAddress"),
        city=item.get("city"),
        state=state,
        zip_code=item.get("zipcode") or item.get("zip"),
        county=county,
        living_sqft=float(item["livingArea"]) if item.get("livingArea") else None,
        year_built=int(item["yearBuilt"]) if item.get("yearBuilt") else None,
        market_value=float(item["price"]) if item.get("price") else None,
        bedrooms=item.get("bedrooms"),
        bathrooms=item.get("bathrooms"),
        latitude=item.get("latitude"),
        longitude=item.get("longitude"),
        description=item.get("description"),
        last_seen=datetime.utcnow(),
        raw={"units": item.get("units"), "raw": item},
    )


class ZillowMultifamily(BaseScraper):
    slug = "multifamily.zillow"
    name = "Zillow (multi-family residential)"
    category = "multifamily"
    expected_min_count = 20
    requires_apify = True
    timeout_s = 480.0

    async def fetch(self) -> Iterable[Listing]:
        per_county = max(1, cap("zillow_multifamily", 500) // len(COUNTY_SLUGS))
        out: list[Listing] = []
        for slug, state, county in COUNTY_SLUGS:
            url = (
                f"https://www.zillow.com/homes/{slug}/multi-family_type/"
                "?searchQueryState=%7B%22filterState%22%3A%7B%22mf%22%3A%7B%22value%22%3Atrue%7D%7D%7D"
            )
            items = await run_actor_sync(
                ACTOR_ID,
                {
                    "startUrls": [{"url": url}],
                    "maxItems": per_county,
                    "searchOptions": {"useFilters": False},
                },
                timeout_s=180,
            )
            for it in items:
                li = _to_listing(it, state, county)
                if li and li.source_url and in_scope(county, state):
                    out.append(li)
        return out
