"""FREE Zillow zestimate enrichment via stealth-browser search.

The board has 31k+ listings with Zillow photos but ZERO zestimates. All
competitors (PropStream, Goliath, etc.) show estimated values. This enricher
fills that gap for free by hitting Zillow's address-search page via
StealthyFetcher (camoufox real browser, bypasses PerimeterX) and extracting
the __NEXT_DATA__ JSON which contains zestimate, rentZestimate, beds, baths,
sqft, year built, lot size, tax assessed value, and home type.

DESIGN:
  - Runs AFTER initial enrichment, BEFORE valuation/calc.
  - Only enriches listings that have an address but no existing zestimate.
  - Idempotent: skips leads that already have raw['zillow']['zestimate'].
  - Capped per run (env ZESTIMATE_MAX_PER_RUN, default 500) and wall-clock
    bounded (env ZESTIMATE_MAX_SECONDS, default 900s).
  - Uses the shared RENDER_CONCURRENCY semaphore (2 concurrent browsers).
  - Politeness: random 1-3s delay between requests.

ACCURACY: zestimate is Zillow's automated valuation model (AVM). It's a
good anchor for ARV but not definitive. The valuation/calc.py pipeline
already weights recorded sales > scraped comps > zestimate > tax assessed,
so this feeds the lowest-priority tier — exactly where an AVM belongs.

USAGE: add to main.py enrichment phases:
    from .enrichment_zestimate import enrich_zestimates
    await asyncio.wait_for(enrich_zestimates(enriched),
                           timeout=float(os.environ.get("ZESTIMATE_MAX_SECONDS", "900")))
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

import structlog

from .http_client import get_text_impersonate
from .models import Listing

log = structlog.get_logger()

_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.S,
)

# Zillow's search URL: address + city/state returns a redirect to the
# property detail page if a match is found, or a search results page.
_SEARCH_URL = "https://www.zillow.com/homes/{query}_rb/"

# Cap per run (each hit is one browser render ~3-8s).
_MAX_PER_RUN = int(os.environ.get("ZESTIMATE_MAX_PER_RUN", "500"))
_BUDGET_S = float(os.environ.get("ZESTIMATE_MAX_SECONDS", "900"))


def _extract_zestimate_from_next_data(html: str) -> Optional[dict]:
    """Parse __NEXT_DATA__ JSON from a Zillow page and extract value fields.

    Works on BOTH detail pages and search results pages. On detail pages the
    data lives at props.pageProps.componentJson.data.property. On search
    results pages it's in cat1.searchResults.listResults[0] (first match).
    """
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except (ValueError, json.JSONDecodeError):
        return None

    props = data.get("props") or {}
    page_props = props.get("pageProps") or {}

    # Path 1: Detail page — property data is nested deep.
    # Try several known paths (Zillow changes these between deployments).
    for path_fn in (_detail_path_a, _detail_path_b, _detail_path_c):
        try:
            prop = path_fn(page_props)
            if prop and isinstance(prop, dict):
                result = _extract_fields(prop)
                if result and result.get("zestimate"):
                    return result
        except (KeyError, TypeError, IndexError):
            continue

    # Path 2: Search results page — first listing is the best match.
    try:
        search_state = page_props.get("searchPageState") or {}
        cat1 = search_state.get("cat1") or {}
        results = cat1.get("searchResults") or {}
        listings = results.get("listResults") or results.get("mapResults") or []
        if listings and isinstance(listings[0], dict):
            item = listings[0]
            home_info = (item.get("hdpData") or {}).get("homeInfo") or {}
            zestimate = (
                item.get("unformattedPrice")  # if for sale, price is asking
                or home_info.get("zestimate")
                or home_info.get("homeValue")
            )
            rent_zestimate = home_info.get("rentZestimate")
            result = {
                "zpid": str(item.get("zpid") or home_info.get("zpid") or ""),
                "zestimate": zestimate if isinstance(zestimate, (int, float)) and zestimate > 0 else None,
                "rent_zestimate": rent_zestimate if isinstance(rent_zestimate, (int, float)) else None,
                "bedrooms": item.get("beds") or home_info.get("bedrooms"),
                "bathrooms": item.get("baths") or home_info.get("bathrooms"),
                "living_sqft": item.get("area") or home_info.get("livingArea"),
                "lot_size_sqft": home_info.get("lotAreaValue"),
                "year_built": home_info.get("yearBuilt"),
                "home_type": home_info.get("homeType"),
                "tax_assessed_value": home_info.get("taxAssessedValue"),
                "detail_url": item.get("detailUrl"),
            }
            if result.get("zestimate"):
                return result
    except (KeyError, TypeError):
        pass

    return None


def _detail_path_a(pp: dict) -> dict:
    """Newest path: componentJson.data.property"""
    return pp["componentJson"]["data"]["property"]


def _detail_path_b(pp: dict) -> dict:
    """Older path: pageProps.propertyDetails"""
    return pp["propertyDetails"]


def _detail_path_c(pp: dict) -> dict:
    """GraphQL path: pageProps.data.property"""
    return pp["data"]["property"]


def _extract_fields(prop: dict) -> Optional[dict]:
    """Extract common fields from a Zillow property detail JSON object."""
    zestimate = (
        prop.get("zestimate")
        or prop.get("homeValue")
        or prop.get("zestimateValue")
    )
    # Some detail pages nest zestimate under "price"
    if not zestimate:
        price = prop.get("price") or {}
        if isinstance(price, dict):
            zestimate = price.get("value")
        elif isinstance(price, (int, float)):
            zestimate = price

    rent = prop.get("rentZestimate") or prop.get("rentEstimate")

    return {
        "zpid": str(prop.get("zpid") or ""),
        "zestimate": zestimate if isinstance(zestimate, (int, float)) and zestimate > 0 else None,
        "rent_zestimate": rent if isinstance(rent, (int, float)) else None,
        "bedrooms": prop.get("bedrooms"),
        "bathrooms": prop.get("bathrooms"),
        "living_sqft": prop.get("livingArea") or prop.get("area"),
        "lot_size_sqft": prop.get("lotSize") or prop.get("lotAreaValue"),
        "year_built": prop.get("yearBuilt"),
        "home_type": prop.get("homeType") or prop.get("type"),
        "tax_assessed_value": prop.get("taxAssessedValue"),
        "detail_url": prop.get("url") or prop.get("detailUrl"),
    }


def _apply_zestimate(li: Listing, data: dict) -> None:
    """Write extracted Zillow data onto the listing, never overwriting good data."""
    if not isinstance(li.raw, dict):
        li.raw = {}

    # Store the full payload under raw['zillow']
    z = li.raw.get("zillow")
    if not isinstance(z, dict):
        z = {}
        li.raw["zillow"] = z
    z.update({k: v for k, v in data.items() if v is not None})

    # Backfill top-level fields only if empty (don't overwrite better data)
    def maybe(attr: str, val):
        if val in (None, "", 0):
            return
        cur = getattr(li, attr, None)
        if cur in (None, "", 0):
            setattr(li, attr, val)

    maybe("bedrooms", data.get("bedrooms"))
    maybe("bathrooms", data.get("bathrooms"))
    maybe("living_sqft", data.get("living_sqft"))
    maybe("year_built", data.get("year_built"))
    maybe("lot_size_sqft", data.get("lot_size_sqft"))
    maybe("market_value", data.get("zestimate"))

    z["zestimate_enriched_at"] = datetime.utcnow().isoformat() + "Z"


async def _fetch_one(li: Listing) -> Optional[dict]:
    """Fetch zestimate for a single listing via stealth browser render."""
    if not li.street_address or not li.state:
        return None

    # Build search query: "123 Main St, Asheville, NC"
    parts = [li.street_address]
    if li.city:
        parts.append(f"{li.city}, {li.state}")
    else:
        parts.append(li.state)
    if li.zip_code:
        parts[0] = f"{li.street_address}, {li.zip_code}"
    query = ", ".join(parts)
    url = _SEARCH_URL.format(query=quote_plus(query))

    try:
        from .render import fetch_rendered
        html = await fetch_rendered(url)
    except Exception as exc:
        log.debug("zestimate.render_error",
                  address=li.street_address[:60],
                  error=str(exc)[:120])
        return None

    if not html or len(html) < 2000:
        return None

    return _extract_zestimate_from_next_data(html)


async def enrich_zestimates(listings: list[Listing]) -> dict:
    """Enrich listings with Zillow zestimates via stealth-browser address search.

    Returns stats dict for run_health.json.
    """
    stats = {
        "eligible": 0,
        "attempted": 0,
        "succeeded": 0,
        "skipped_existing": 0,
        "failed": 0,
    }

    # Filter: only listings with an address and no existing zestimate.
    eligible = []
    for li in listings:
        if not li.street_address or not li.state:
            continue
        raw = li.raw if isinstance(li.raw, dict) else {}
        z = raw.get("zillow")
        if isinstance(z, dict) and z.get("zestimate"):
            stats["skipped_existing"] += 1
            continue
        eligible.append(li)

    stats["eligible"] = len(eligible)
    if not eligible:
        log.info("zestimate.no_eligible", skipped_existing=stats["skipped_existing"])
        return stats

    # Cap per run
    targets = eligible[:_MAX_PER_RUN]
    stats["eligible"] = len(eligible)
    stats["capped_to"] = len(targets)

    log.info("zestimate.start",
             eligible=stats["eligible"],
             targets=len(targets),
             skipped_existing=stats["skipped_existing"],
             max_per_run=_MAX_PER_RUN,
             budget_s=_BUDGET_S)

    for li in targets:
        stats["attempted"] += 1
        try:
            data = await _fetch_one(li)
        except Exception as exc:
            log.warning("zestimate.fetch_failed",
                        address=li.street_address[:60],
                        error=str(exc)[:200])
            stats["failed"] += 1
            continue

        if data and data.get("zestimate"):
            _apply_zestimate(li, data)
            stats["succeeded"] += 1
            log.debug("zestimate.hit",
                      address=li.street_address[:50],
                      zestimate=data["zestimate"])
        else:
            stats["failed"] += 1

        # Politeness delay
        await asyncio.sleep(random.uniform(0.5, 2.0))

    log.info("zestimate.done", **stats)
    return stats
