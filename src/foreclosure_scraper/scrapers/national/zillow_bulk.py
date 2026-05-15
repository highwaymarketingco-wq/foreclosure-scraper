"""Zillow RECENTLY-SOLD foreclosure comps (NC + SC).

Companion to `zillow_foreclosures` which scrapes the active listings. This
scraper hits the recently-sold view filtered to foreclosures:

  /{state.lower()}/sold/foreclosures/[{N}_p/]

Same Scrapling + __NEXT_DATA__ extraction pattern. Each row is treated
as REO/sold-comp — feeds the sold-pool comp-matching pipeline rather
than the active leads pool.

Capped at ZILLOW_SOLD_PAGES env (default 3) per state to keep runtime
under ~90s. Zillow shows ~20 total pages per state in NC; bumping the
cap pulls more comps at the cost of run time.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.S,
)


def _kind(label: str | None) -> PropertyKind:
    if not label:
        return PropertyKind.UNKNOWN
    s = label.lower()
    if "single" in s or "house" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "multi" in s or "duplex" in s:
        return PropertyKind.MULTI_FAMILY
    if "manufactured" in s or "mobile" in s:
        return PropertyKind.MOBILE
    if "land" in s or "lot" in s:
        return PropertyKind.LAND
    return PropertyKind.UNKNOWN


def _to_listing(item: dict, state: str, slug: str) -> Listing | None:
    addr_street = (item.get("addressStreet") or "").strip()
    if not addr_street:
        return None
    region = (item.get("addressState") or state).strip().upper()
    if region != state:
        return None
    zpid = str(item.get("zpid") or "").strip() or None
    lat_lng = item.get("latLong") or {}
    price = item.get("unformattedPrice")
    home_info = (item.get("hdpData") or {}).get("homeInfo") or {}
    img = item.get("imgSrc") or ""
    photos = [img] if isinstance(img, str) and img.startswith("http") else []
    return Listing(
        source=slug,
        source_url=item.get("detailUrl") or f"https://www.zillow.com/{state.lower()}/sold/foreclosures/",
        listing_type=ListingType.REO,  # sold comp
        property_kind=_kind(home_info.get("homeType")),
        state=region,
        city=(item.get("addressCity") or "").strip() or None,
        zip_code=(item.get("addressZipcode") or "").strip() or None,
        street_address=addr_street,
        case_number=f"zillow-sold-{zpid}" if zpid else None,
        latitude=lat_lng.get("latitude") if isinstance(lat_lng.get("latitude"), (int, float)) else None,
        longitude=lat_lng.get("longitude") if isinstance(lat_lng.get("longitude"), (int, float)) else None,
        opening_bid=price if isinstance(price, (int, float)) else None,
        description=(
            f"Zillow sold foreclosure comp ({item.get('statusText') or 'Sold'}) — "
            f"{item.get('beds') or ''}bd/{item.get('baths') or ''}ba "
            f"{item.get('area') or ''} sqft"
        ).strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "zpid": zpid,
            "marketing_status": item.get("marketingStatusSimplifiedCd"),
            "status_text": item.get("statusText"),
            "home_type": home_info.get("homeType"),
            "beds": item.get("beds"),
            "baths": item.get("baths"),
            "area": item.get("area"),
            "sold_comp": True,
            "images": {"real": photos} if photos else {},
        },
    )


def _parse_page(html: str, state: str, slug: str) -> tuple[list[Listing], int]:
    m = NEXT_DATA_RE.search(html)
    if not m:
        return [], 0
    try:
        data = json.loads(m.group(1))
    except (ValueError, json.JSONDecodeError):
        return [], 0
    try:
        search_state = data["props"]["pageProps"]["searchPageState"]
        cat1 = search_state["cat1"]
        results = cat1["searchResults"]
    except (KeyError, TypeError):
        return [], 0
    list_results = results.get("listResults") or results.get("mapResults") or []
    total_pages = (cat1.get("searchList") or {}).get("totalPages") or 0
    listings = []
    for item in list_results:
        if not isinstance(item, dict):
            continue
        li = _to_listing(item, state, slug)
        if li is not None:
            listings.append(li)
    return listings, total_pages


async def _fetch_state(state: str, slug: str, max_pages: int) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []

    base = f"https://www.zillow.com/{state.lower()}/sold/foreclosures"
    out: list[Listing] = []
    seen: set[str] = set()
    total_pages = 0
    for page in range(1, max_pages + 1):
        if page > 1 and page > total_pages:
            break
        url = f"{base}/" if page == 1 else f"{base}/{page}_p/"
        try:
            result = await StealthyFetcher.async_fetch(
                url, headless=True, network_idle=False, timeout=90000,
                solve_cloudflare=False,
            )
        except Exception as exc:
            log.warning("zillow_bulk.fetch_fail", state=state, page=page,
                        error=str(exc)[:200])
            break
        body = getattr(result, "body", b"")
        html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
        if not html or len(html) < 5000:
            break
        listings, tp = _parse_page(html, state, slug)
        if page == 1:
            total_pages = tp
        new = 0
        for li in listings:
            k = li.case_number or li.source_url
            if k in seen:
                continue
            seen.add(k)
            out.append(li)
            new += 1
        if new == 0:
            break
    log.info("zillow_bulk.state_done", state=state, count=len(out),
             pages_walked=page if total_pages else 1, total_pages=total_pages)
    return out


class ZillowBulk(BaseScraper):
    slug = "national.zillow_bulk"
    name = "Zillow Sold Foreclosure Comps (NC + SC)"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    requires_render = True
    timeout_s = 900.0

    async def fetch(self) -> Iterable[Listing]:
        max_pages = int(os.environ.get("ZILLOW_SOLD_PAGES", "3"))
        out: list[Listing] = []
        for state in ("NC", "SC"):
            try:
                out.extend(await _fetch_state(state, self.slug, max_pages))
            except Exception as exc:
                log.warning("zillow_bulk.state_failed", state=state, error=str(exc)[:200])
        return out
