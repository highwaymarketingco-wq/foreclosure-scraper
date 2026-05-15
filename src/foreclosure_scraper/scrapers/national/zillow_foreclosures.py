"""Zillow foreclosures (NC + SC) via Scrapling stealth + __NEXT_DATA__.

Zillow blocks plain HTTP with PerimeterX, but Scrapling's stealth mode
gets past the gate on the public state-foreclosure listing pages. The
listings are embedded in the page's `__NEXT_DATA__` script tag:

  props.pageProps.searchPageState.cat1.searchResults.listResults

Each entry contains:
  zpid, addressStreet, addressCity, addressState, addressZipcode,
  unformattedPrice, beds, baths, area, latLong, statusType, statusText,
  marketingStatusSimplifiedCd ("Pre-Foreclosure", "Foreclosure", "Auction",
  "Bank Owned (REO)"), detailUrl, hdpData.homeInfo.{...}

We paginate until totalPages is reached (typically ~6 per state). On a
residential IP Scrapling generally succeeds; on a datacenter IP it gets
captcha'd and yields []. The expected_min_count is 0 to avoid REGRESSED
noise on captcha runs.
"""
from __future__ import annotations

import json
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


def _ltype(marketing_status: str | None) -> ListingType:
    if not marketing_status:
        return ListingType.UNKNOWN
    s = marketing_status.lower()
    if "auction" in s:
        return ListingType.AUCTION
    if "reo" in s or "bank owned" in s:
        return ListingType.REO
    if "pre-foreclosure" in s or "pre foreclosure" in s:
        return ListingType.LIS_PENDENS
    if "foreclosure" in s:
        return ListingType.FORECLOSURE_SALE
    return ListingType.UNKNOWN


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
    # Zillow's hdpData.homeInfo doesn't carry county for most listings.
    # Try the field, then fall back to a city->county lookup for our
    # coastal scope so the oceanfront override in main._in_scope can fire.
    county = (home_info.get("county") or "").strip() or None
    if county and county.lower().endswith(" county"):
        county = county[:-7].strip()
    if not county:
        from ..._coastal_city_to_county import coastal_county_for
        county = coastal_county_for(
            (item.get("addressCity") or "").strip(),
            region,
        )
    return Listing(
        source=slug,
        source_url=item.get("detailUrl") or f"https://www.zillow.com/{state.lower()}/foreclosures/",
        listing_type=_ltype(item.get("marketingStatusSimplifiedCd")),
        property_kind=_kind(home_info.get("homeType")),
        state=region,
        county=county,
        city=(item.get("addressCity") or "").strip() or None,
        zip_code=(item.get("addressZipcode") or "").strip() or None,
        street_address=addr_street,
        case_number=f"zillow-{zpid}" if zpid else None,
        latitude=lat_lng.get("latitude") if isinstance(lat_lng.get("latitude"), (int, float)) else None,
        longitude=lat_lng.get("longitude") if isinstance(lat_lng.get("longitude"), (int, float)) else None,
        opening_bid=price if isinstance(price, (int, float)) else None,
        description=(
            f"Zillow foreclosure ({item.get('statusText') or 'For Sale'}) — "
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
            "images": {"real": photos} if photos else {},
        },
    )


def _extract_next_data(html: str) -> dict | None:
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except (ValueError, json.JSONDecodeError):
        return None


def _parse_page(html: str, state: str, slug: str) -> tuple[list[Listing], int]:
    """Returns (listings, total_pages). total_pages = 0 on failure."""
    data = _extract_next_data(html)
    if not data:
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


async def _fetch_state(state: str, slug: str) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("zillow.scrapling_missing")
        return []

    base = f"https://www.zillow.com/{state.lower()}/foreclosures"
    out: list[Listing] = []
    seen: set[str] = set()
    total_pages = 0
    for page in range(1, 11):  # hard cap 10 pages; Zillow shows ~6
        if page > 1 and page > total_pages:
            break
        url = f"{base}/" if page == 1 else f"{base}/{page}_p/"
        try:
            result = await StealthyFetcher.async_fetch(
                url, headless=True, network_idle=False, timeout=90000,
                solve_cloudflare=False,
            )
        except Exception as exc:
            log.warning("zillow.fetch_fail", state=state, page=page, error=str(exc)[:200])
            break
        body = getattr(result, "body", b"")
        html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
        if not html or len(html) < 5000:
            break
        listings, tp = _parse_page(html, state, slug)
        if not listings and page == 1:
            log.warning("zillow.empty_first_page", state=state)
            break
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
    log.info("zillow.state_done", state=state, count=len(out), total_pages=total_pages)
    return out


class ZillowForeclosures(BaseScraper):
    slug = "national.zillow_foreclosures"
    name = "Zillow Foreclosures (NC + SC)"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    requires_render = True
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in ("NC", "SC"):
            try:
                out.extend(await _fetch_state(state, self.slug))
            except Exception as exc:
                log.warning("zillow.state_failed", state=state, error=str(exc)[:200])
        return out
