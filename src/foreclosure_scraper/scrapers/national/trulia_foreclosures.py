"""Trulia foreclosures — geo-detected best-effort probe.

Trulia (Zillow subsidiary) does NOT honor state-level URL filters for
foreclosures; /foreclosures/NC and /for_sale/NC/FORECLOSURE_LISTING_TYPE_filter
both redirect to non-filtered state-listing pages. The only working
filter is geo: `/foreclosures/` returns ~16 foreclosure listings localized
to the requester's IP. Run from a residential NC or SC IP, that yields
NC or SC listings respectively — the trade-off is small per-run yield
(~16) but zero engineering cost vs Zillow's pagination.

For real NC/SC coverage rely on `zillow_foreclosures` (340+ listings).
This scraper is the long-shot complement.

Parses the embedded __NEXT_DATA__ block at
  props.searchData.homes[*]
Each item has location, price, beds/baths, currentStatus.isForeclosure,
tags (AUCTION / FORECLOSURE / etc.). We filter to homes where
currentStatus.isForeclosure is True.
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

URL = "https://www.trulia.com/foreclosures/"
NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.S,
)


def _ltype_from_tags(tags: list[dict] | None) -> ListingType:
    if not tags:
        return ListingType.FORECLOSURE_SALE
    names = " ".join((t.get("formattedName") or "").upper() for t in tags if isinstance(t, dict))
    if "AUCTION" in names:
        return ListingType.AUCTION
    if "REO" in names or "BANK OWNED" in names:
        return ListingType.REO
    if "PRE-FORECLOSURE" in names or "PRE FORECLOSURE" in names:
        return ListingType.LIS_PENDENS
    return ListingType.FORECLOSURE_SALE


def _to_listing(h: dict, slug: str) -> Listing | None:
    status = h.get("currentStatus") or {}
    if not status.get("isForeclosure"):
        return None
    loc = h.get("location") or {}
    state = (loc.get("stateCode") or "").strip().upper()
    if state not in ("NC", "SC"):
        return None
    addr_street = (loc.get("streetAddress") or "").strip() or None
    if not addr_street:
        return None
    coords = loc.get("coordinates") or {}
    home_id = h.get("typedHomeId") or h.get("providerListingId")
    href = h.get("url") or h.get("homeUrl") or ""
    price_obj = h.get("price") or {}
    price_str = (price_obj.get("formattedPrice") or "").replace("$", "").replace(",", "").strip()
    try:
        price = float(re.match(r"^\d+(\.\d+)?", price_str).group(0)) if price_str else None
    except Exception:
        price = None
    # Photo: media.heroImage.url.medium (or small fallback)
    photos: list[str] = []
    media = h.get("media") or {}
    hero = (media.get("heroImage") or {}) if isinstance(media, dict) else {}
    url_obj = hero.get("url") or {}
    img_url = url_obj.get("medium") or url_obj.get("small") if isinstance(url_obj, dict) else None
    if isinstance(img_url, str) and img_url.startswith("http"):
        photos.append(img_url)
    return Listing(
        source=slug,
        source_url=f"https://www.trulia.com{href}" if href.startswith("/") else (href or URL),
        listing_type=_ltype_from_tags(h.get("fullTags") or h.get("tags")),
        property_kind=PropertyKind.UNKNOWN,
        state=state,
        city=(loc.get("city") or "").strip() or None,
        zip_code=(loc.get("zipCode") or "").strip() or None,
        street_address=addr_street,
        case_number=f"trulia-{home_id}" if home_id else None,
        latitude=coords.get("latitude") if isinstance(coords.get("latitude"), (int, float)) else None,
        longitude=coords.get("longitude") if isinstance(coords.get("longitude"), (int, float)) else None,
        opening_bid=price,
        description=(
            f"Trulia foreclosure ({', '.join((t.get('formattedName') or '') for t in (h.get('fullTags') or []) if isinstance(t, dict)) or 'Foreclosure'})"
        ),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "trulia_id": home_id,
            "is_foreclosure": True,
            "is_recently_sold": status.get("isRecentlySold"),
            "images": {"real": photos} if photos else {},
        },
    )


async def _fetch_page() -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []
    try:
        result = await StealthyFetcher.async_fetch(
            URL, headless=True, network_idle=False, timeout=90000,
            solve_cloudflare=False,
        )
    except Exception as exc:
        log.warning("trulia.fetch_failed", error=str(exc)[:200])
        return []
    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html or len(html) < 5000:
        return []
    m = NEXT_DATA_RE.search(html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except (ValueError, json.JSONDecodeError):
        return []
    homes = (data.get("props") or {}).get("searchData", {}).get("homes") or []
    out: list[Listing] = []
    for h in homes:
        if not isinstance(h, dict):
            continue
        li = _to_listing(h, "national.trulia")
        if li is not None:
            out.append(li)
    return out


class TruliaForeclosures(BaseScraper):
    slug = "national.trulia"
    name = "Trulia Foreclosures (geo-detected)"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    requires_render = True
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        listings = await _fetch_page()
        log.info("trulia.done", total=len(listings))
        return listings
