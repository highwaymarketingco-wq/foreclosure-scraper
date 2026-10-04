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

FOUND 2026-10-04 (HERMES extraction-completeness audit, national batch 5):
this module is a near-line-for-line sibling of `zillow_foreclosures.py`,
which batch 18 (2026-10-04) audited and fixed for the exact same two bug
classes. Both are confirmed to apply here too, unfixed until now:

1. **An 8th instance this session of the RAW_KEEP silent-drop pattern**: a
   direct `_slim_raw()` round-trip confirms `marketing_status`/`status_text`/
   `home_type`/`beds`/`baths`/`area`/`sold_comp` were all flat top-level
   `raw` keys with NO RAW_KEEP entry (only `zpid` and `images` were ever
   registered) -- silently dropped at every publish since this scraper was
   built. Fixed by namespacing them under a new registered
   `"zillow_bulk"` key, same pattern as the sibling's `"zillow_foreclosures"`
   key.
2. **The same richly-detailed, zero-marginal-cost fields the sibling found
   unused on the same already-fetched item**: `carouselPhotosComposable`
   (the FULL photo gallery) vs. the single `imgSrc` kept before;
   `zestimate` -> `market_value`; `hdpData.homeInfo.lotAreaValue`/
   `lotAreaUnit` -> `lot_size_sqft`; `brokerName` (a contactability signal);
   `beds`/`baths`/`area` promoted to first-class `bedrooms`/`bathrooms`/
   `living_sqft` fields (previously only ever in raw, so a `_slim_raw()`
   drop meant they never reached the board at all); `isNonOwnerOccupied`/
   `isZillowOwned`/`daysOnZillow`/`rentZestimate`. Unlike the sibling, no
   `_ltype()` classification fix is needed here -- this scraper always
   hardcodes `listing_type=REO` (it feeds the sold-comp pool, not the active
   leads pool), so `marketingStatusSimplifiedCd`'s UI-badge-vs-stage-category
   confusion batch 18 found never affected this file's actual classification,
   only its (now-fixed) raw-key survival.
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


def _acres_to_sqft(value, unit: str | None) -> float | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    u = (unit or "").strip().lower()
    if u.startswith("acre"):
        return float(value) * 43560.0
    if u.startswith("sqft") or u.startswith("sq ft") or u == "":
        return float(value)
    return None


def _photo_gallery(item: dict) -> list[str]:
    """Same helper as zillow_foreclosures.py's `_photo_gallery()` --
    `carouselPhotosComposable` carries the FULL gallery (a baseUrl template +
    photoKey list), confirmed live to be a real, directly-fetchable JPEG with
    no auth needed."""
    cp = item.get("carouselPhotosComposable")
    if not isinstance(cp, dict):
        return []
    base = cp.get("baseUrl")
    photo_data = cp.get("photoData")
    if not isinstance(base, str) or "{photoKey}" not in base or not isinstance(photo_data, list):
        return []
    out = []
    for p in photo_data:
        if isinstance(p, dict) and isinstance(p.get("photoKey"), str) and p["photoKey"]:
            out.append(base.replace("{photoKey}", p["photoKey"]))
    return out

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
    # FOUND 2026-10-04 (batch 5, see module docstring): carouselPhotosComposable
    # carries the FULL gallery; fall back to the single imgSrc only when the
    # gallery is absent/empty (same fix as the zillow_foreclosures sibling).
    photos = _photo_gallery(item)
    if not photos:
        img = item.get("imgSrc") or ""
        photos = [img] if isinstance(img, str) and img.startswith("http") else []
    zestimate = item.get("zestimate")
    lot_sqft = _acres_to_sqft(home_info.get("lotAreaValue"), home_info.get("lotAreaUnit"))
    # Zillow's hdpData.homeInfo doesn't carry county for most listings --
    # same gap confirmed live 2026-10-01 in the sibling national.
    # zillow_foreclosures (282/310 NC rows, 91%, had no county at all),
    # which silently drops real in-footprint leads at the scope gate
    # (FORECLOSURE_SALE/AUCTION/REO are "flip" types that need a county to
    # even attempt in_scope() matching). This scraper feeds the sold-comp
    # pool rather than the active-leads pool, but the same county-blank
    # admission problem applies, so the same two-tier fallback is used:
    # upstate_county_for (our actual core WNC/upstate-SC footprint) first,
    # coastal second.
    county = (home_info.get("county") or "").strip() or None
    if county and county.lower().endswith(" county"):
        county = county[:-7].strip()
    if not county:
        from ..._upstate_city_to_county import upstate_county_for
        county = upstate_county_for(
            (item.get("addressCity") or "").strip(),
            region,
        )
    if not county:
        from ..._coastal_city_to_county import coastal_county_for
        county = coastal_county_for(
            (item.get("addressCity") or "").strip(),
            region,
        )
    return Listing(
        source=slug,
        source_url=item.get("detailUrl") or f"https://www.zillow.com/{state.lower()}/sold/foreclosures/",
        listing_type=ListingType.REO,  # sold comp
        property_kind=_kind(home_info.get("homeType")),
        state=region,
        county=county,
        city=(item.get("addressCity") or "").strip() or None,
        zip_code=(item.get("addressZipcode") or "").strip() or None,
        street_address=addr_street,
        case_number=f"zillow-sold-{zpid}" if zpid else None,
        latitude=lat_lng.get("latitude") if isinstance(lat_lng.get("latitude"), (int, float)) else None,
        longitude=lat_lng.get("longitude") if isinstance(lat_lng.get("longitude"), (int, float)) else None,
        opening_bid=price if isinstance(price, (int, float)) else None,
        # FOUND 2026-10-04 (batch 5): beds/baths/area were only ever in raw
        # (and raw-dropped at that, see below) -- promote to first-class
        # fields, same as the zillow_foreclosures sibling.
        bedrooms=item.get("beds") if isinstance(item.get("beds"), (int, float)) else None,
        bathrooms=item.get("baths") if isinstance(item.get("baths"), (int, float)) else None,
        living_sqft=item.get("area") if isinstance(item.get("area"), (int, float)) else None,
        market_value=float(zestimate) if isinstance(zestimate, (int, float)) and zestimate > 0 else None,
        lot_size_sqft=lot_sqft,
        description=(
            f"Zillow sold foreclosure comp ({item.get('statusText') or 'Sold'}) — "
            f"{item.get('beds') or ''}bd/{item.get('baths') or ''}ba "
            f"{item.get('area') or ''} sqft"
        ).strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "zpid": zpid,
            "sold_comp": True,
            "images": {"real": photos} if photos else {},
            # FOUND 2026-10-04 (batch 5): marketing_status/status_text/
            # home_type/beds/baths/area were all flat top-level raw keys with
            # NO RAW_KEEP entry -- a direct _slim_raw() round-trip confirmed
            # only zpid/images survived publish, silently dropping the rest
            # on every row since this scraper was built (same bug as the
            # zillow_foreclosures sibling before batch 18's fix). Namespaced
            # under a new registered "zillow_bulk" key; also adds brokerName/
            # isNonOwnerOccupied/isZillowOwned/daysOnZillow/rentZestimate,
            # all free, all previously unread on the same item.
            "zillow_bulk": {
                "marketing_status": item.get("marketingStatusSimplifiedCd"),
                "status_text": item.get("statusText"),
                "status_type": item.get("statusType"),
                "home_type": home_info.get("homeType"),
                "beds": item.get("beds"),
                "baths": item.get("baths"),
                "area": item.get("area"),
                "broker_name": item.get("brokerName"),
                "is_non_owner_occupied": home_info.get("isNonOwnerOccupied"),
                "is_zillow_owned": home_info.get("isZillowOwned"),
                "days_on_zillow": home_info.get("daysOnZillow"),
                "rent_zestimate": home_info.get("rentZestimate"),
            },
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
