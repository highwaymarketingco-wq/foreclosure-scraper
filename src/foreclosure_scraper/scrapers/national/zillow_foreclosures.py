"""Zillow foreclosures (NC + SC) via Scrapling stealth + __NEXT_DATA__.

Zillow blocks plain HTTP with PerimeterX, but Scrapling's stealth mode
gets past the gate on the public state-foreclosure listing pages. The
listings are embedded in the page's `__NEXT_DATA__` script tag:

  props.pageProps.searchPageState.cat1.searchResults.listResults

Each entry contains:
  zpid, addressStreet, addressCity, addressState, addressZipcode,
  unformattedPrice, beds, baths, area, latLong, statusType, statusText,
  marketingStatusSimplifiedCd, detailUrl, brokerName,
  carouselPhotosComposable.{baseUrl, photoData[].photoKey}, zestimate,
  hdpData.homeInfo.{homeType, listing_sub_type, isNonOwnerOccupied,
  isZillowOwned, daysOnZillow, lotAreaValue, lotAreaUnit, rentZestimate,
  ...}

We paginate until totalPages is reached (typically ~6 per state). On a
residential IP Scrapling generally succeeds; on a datacenter IP it gets
captcha'd and yields []. The expected_min_count is 0 to avoid REGRESSED
noise on captcha runs.

FOUND 2026-10-04 (HERMES extraction-completeness audit, batch 18), live-
investigated via a real browser session (not this machine's local
Scrapling/StealthyFetcher, which needs a headless Chromium render --
skipped per this machine's RAM constraint; www.zillow.com/nc/foreclosures/
loaded cleanly with no captcha via the session's own cloud-hosted browser,
SC got captcha-blocked that same check, matching this module's own
documented residential-vs-datacenter-IP note):

1. **A severe, live-reproduced classification bug**, not previously
   documented: this module's own docstring assumed
   marketingStatusSimplifiedCd carries one of "Pre-Foreclosure"/
   "Foreclosure"/"Auction"/"Bank Owned (REO)". On the real current page (41
   live NC rows), the ACTUAL values are "RecentChange" (23/41, 56%),
   "Pre-Foreclosure - RecentChange" (17/41), and "Non Owner Occupied"
   (1/41) -- UI/marketing badges, not stable foreclosure-stage categories.
   "RecentChange" and "Non Owner Occupied" match NONE of `_ltype()`'s old
   keyword checks, so the MAJORITY of real current listings (24/41, 59%)
   were silently classified `ListingType.UNKNOWN`. The real, reliable
   signal was sitting one level down, unused: every one of the same 41
   rows' `hdpData.homeInfo.listing_sub_type` carries exactly one of
   `is_bankOwned`/`is_foreclosure`/`is_forAuction` (never more than one,
   confirmed by cross-tabulating all 41 rows) -- a clean, structured, same-
   cost classifier. `_ltype()` now checks `listing_sub_type` FIRST, falling
   back to the old marketingStatusSimplifiedCd text match only when
   `listing_sub_type` is absent (defense in depth, not a regression if
   Zillow's schema drifts again).
2. **A 7th instance this session of the RAW_KEEP silent-drop pattern**:
   `marketing_status`/`status_text`/`home_type`/`beds`/`baths`/`area` were
   ALL flat top-level `raw` keys with no RAW_KEEP entry (only `zpid` and
   `images` were ever registered) -- a direct `_slim_raw()` round-trip
   confirmed 6 of 8 raw keys were silently dropped at every publish since
   this scraper was built. Fixed by namespacing them under a new
   registered `"zillow_foreclosures"` key.
3. **Several richly-detailed, zero-marginal-cost fields found unused on
   the same already-fetched item**: `zestimate` (a real market-value
   estimate, present on 15/41 live rows) -> promoted to `market_value`.
   `hdpData.homeInfo.lotAreaValue`/`lotAreaUnit` (e.g. "0.3533 acres") ->
   promoted to `lot_size_sqft` (acres converted to sqft via the same `*
   43560` convention `servicelink_auction.py` already uses). `brokerName`
   (37/41 live rows, e.g. "NorthGroup Real Estate LLC") -- a real,
   HERMES-sec-9 contactability signal, never captured. `carouselPhoto
   Composable` (`baseUrl` template + `photoData[].photoKey` list) -- the
   FULL photo gallery (one live row carried 23 photos; confirmed live the
   constructed URL `baseUrl.replace("{photoKey}", photoKey)` is a real,
   directly-fetchable JPEG, no auth) vs. the single `imgSrc` previously
   kept. `hdpData.homeInfo.isNonOwnerOccupied`/`isZillowOwned`/
   `daysOnZillow`/`rentZestimate` -- all free, all on the row, never read.
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


def _ltype(marketing_status: str | None, listing_sub_type: dict | None = None) -> ListingType:
    # FOUND 2026-10-04 (batch 18, see module docstring): listing_sub_type is
    # the real, reliable, structured classifier -- marketingStatusSimplifiedCd
    # carries UI/marketing badges on the real current page ("RecentChange",
    # "Non Owner Occupied"), not the stable foreclosure-stage categories this
    # function used to assume. Checked FIRST; every live-sampled row carried
    # exactly one of these three flags, never more than one.
    if isinstance(listing_sub_type, dict):
        if listing_sub_type.get("is_forAuction"):
            return ListingType.AUCTION
        if listing_sub_type.get("is_bankOwned"):
            return ListingType.REO
        if listing_sub_type.get("is_foreclosure"):
            return ListingType.FORECLOSURE_SALE
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
    """FOUND 2026-10-04 (batch 18): carouselPhotosComposable carries the
    FULL photo gallery (a baseUrl template + a list of photoKeys) -- one
    live-sampled row carried 23 photos vs. the single imgSrc previously
    kept. Confirmed live the constructed URL is a real, directly-
    fetchable JPEG with no auth needed."""
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
    # FOUND 2026-10-04 (batch 18): carouselPhotosComposable carries the FULL
    # gallery (up to dozens of photos); fall back to the single imgSrc only
    # when the gallery is absent/empty.
    photos = _photo_gallery(item)
    if not photos:
        img = item.get("imgSrc") or ""
        photos = [img] if isinstance(img, str) and img.startswith("http") else []
    zestimate = item.get("zestimate")
    lot_sqft = _acres_to_sqft(home_info.get("lotAreaValue"), home_info.get("lotAreaUnit"))
    # Zillow's hdpData.homeInfo doesn't carry county for most listings --
    # confirmed live 2026-10-01 (national/reo per-source audit): 282/310 NC
    # rows (91%) had no county at all. FORECLOSURE_SALE/AUCTION/REO are all
    # "flip" listing types (main._FLIP_LISTING_TYPES), which gate on the
    # NARROW in_scope(county, state) check -- and in_scope(None, state) is
    # unconditionally False. That silently dropped real in-footprint leads
    # at the scope gate with no county to even try matching against, e.g.
    # "208 S Ransom St, Gastonia NC" (Gaston county) and "71 Laurel Ridge
    # Dr, Spruce Pine NC" (Mitchell county) -- both live-confirmed present
    # in a real fetch, both in our 18-county footprint, both losing their
    # one shot at admission for want of a county string. Only a coastal
    # fallback existed before; upstate_county_for (the same WNC/upstate-SC
    # gazetteer already used by national.crexi_multifamily and
    # national.estate_sales for this exact problem) is tried FIRST since
    # that is our actual core footprint, coastal second.
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
        source_url=item.get("detailUrl") or f"https://www.zillow.com/{state.lower()}/foreclosures/",
        listing_type=_ltype(item.get("marketingStatusSimplifiedCd"), home_info.get("listing_sub_type")),
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
        # beds/baths/area were only in raw — promote to first-class fields.
        bedrooms=item.get("beds") if isinstance(item.get("beds"), (int, float)) else None,
        bathrooms=item.get("baths") if isinstance(item.get("baths"), (int, float)) else None,
        living_sqft=item.get("area") if isinstance(item.get("area"), (int, float)) else None,
        # FOUND 2026-10-04 (batch 18): zestimate/lot size were on the same
        # already-fetched item, never read. See module docstring.
        market_value=float(zestimate) if isinstance(zestimate, (int, float)) and zestimate > 0 else None,
        lot_size_sqft=lot_sqft,
        description=(
            f"Zillow foreclosure ({item.get('statusText') or 'For Sale'}) — "
            f"{item.get('beds') or ''}bd/{item.get('baths') or ''}ba "
            f"{item.get('area') or ''} sqft"
        ).strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "zpid": zpid,
            "images": {"real": photos} if photos else {},
            # FOUND 2026-10-04 (batch 18): marketing_status/status_text/
            # home_type/beds/baths/area were all flat top-level raw keys --
            # a direct _slim_raw() round-trip confirmed only zpid/images
            # survived publish (neither was in RAW_KEEP), so the rest were
            # silently dropped on every row since this scraper was built.
            # Namespaced under a new registered "zillow_foreclosures" key;
            # also adds brokerName/listing_sub_type/isNonOwnerOccupied/
            # isZillowOwned/daysOnZillow/rentZestimate, all free, all
            # previously unread on the same item.
            "zillow_foreclosures": {
                "marketing_status": item.get("marketingStatusSimplifiedCd"),
                "status_text": item.get("statusText"),
                "status_type": item.get("statusType"),
                "raw_home_status_cd": item.get("rawHomeStatusCd"),
                "home_type": home_info.get("homeType"),
                "listing_sub_type": home_info.get("listing_sub_type"),
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
        # Bank rows as they are collected: if the soft timeout fires,
        # base_scraper ships self.partial instead of discarding the run.
        out = self.partial
        for state in ("NC", "SC"):
            try:
                out.extend(await _fetch_state(state, self.slug))
            except Exception as exc:
                log.warning("zillow.state_failed", state=state, error=str(exc)[:200])
        return out
