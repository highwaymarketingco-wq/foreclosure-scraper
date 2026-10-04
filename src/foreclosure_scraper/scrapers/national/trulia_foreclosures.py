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

FOUND 2026-10-04 (HERMES extraction-completeness audit, national batch 5),
live-verified via the session's own cloud browser against a real current
fetch of trulia.com/foreclosures/ (geo-detected to Spartanburg SC, 14 real
current rows, this machine's local StealthyFetcher render skipped per the
documented RAM constraint). `currentStatus.isForeclosure` itself is intact
(no classification bug) but several real, free, zero-marginal-cost fields
on the SAME already-fetched item were never read:

1. **The REAL photo gallery was never captured.** `_to_listing()` only ever
   read `media.heroImage` (often a Google Street View static image when the
   listing has no real photos at all -- confirmed live on one sampled row:
   `heroImage.url` pointed at `maps.googleapis.com/maps/api/streetview`
   while `media.photos` was `[]`). `media.photos[].url.large` carries the
   REAL gallery when present -- confirmed live up to 24 real trulia.com CDN
   photos on one current row, 0 on the one with the street-view fallback.
2. **Agent/broker contactability was never captured**, though present on
   6 of 7 live-sampled rows (e.g. "Philip M Healy" / "Realty World of The
   Upstate"; "John Slaughter" / "Bid Y'All Auction & Realty") at
   `activeListing.provider.{listingAgent.name, broker.name}`.
3. **A generic, uninformative description was shipped instead of Trulia's
   own real one.** `description.value` carries a genuinely useful sentence
   per listing -- and, live-confirmed, is the ONLY place `lot size` and
   `year built` appear at all on 2 of 7 sampled rows (e.g. "...has a lot
   size of 8712 sqft and was built in 1950" -- no structured `lotSize`
   field was present on that same row). Parsed out via regex and promoted
   to `lot_size_sqft`/`year_built` when those structured fields are absent.
4. **`propertyType.value`** (e.g. "SINGLE_FAMILY_HOME", "LOT_LAND") was
   never read -- `property_kind` was hardcoded UNKNOWN on every row
   regardless. Mapped to the real `PropertyKind`.
5. **`activeListing.dateListed`** (a real listing-freshness ISO date) was
   never read.
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
# Trulia geo-detects from IP and returns ~16 results per fetch. To maximize
# NC+SC coverage, try multiple URL variants that may yield different result
# sets. Each is a best-effort probe — if it returns 0 homes, we move on.
URL_VARIANTS = (
    "https://www.trulia.com/foreclosures/",
    "https://www.trulia.com/foreclosures/Charlotte,NC/",
    "https://www.trulia.com/foreclosures/Raleigh,NC/",
    "https://www.trulia.com/foreclosures/Greenville,SC/",
    "https://www.trulia.com/foreclosures/Columbia,SC/",
    "https://www.trulia.com/foreclosures/Asheville,NC/",
    "https://www.trulia.com/foreclosures/Wilmington,NC/",
    "https://www.trulia.com/foreclosures/Myrtle_Beach,SC/",
)
NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.S,
)


def _num_field(v):
    """Trulia home dimension fields come as a plain number OR a
    {value, formattedValue/formattedDimension} object depending on the graph
    slice. Pull a float defensively; return None when the shape is unclear
    (so a wrong key never yields a wrong value)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        if isinstance(v.get("value"), (int, float)) and not isinstance(v.get("value"), bool):
            return float(v["value"])
        for k in ("formattedValue", "formattedDimension"):
            s = v.get(k)
            if isinstance(s, str):
                m = re.search(r"[\d,]+(?:\.\d+)?", s)
                if m:
                    try:
                        return float(m.group(0).replace(",", ""))
                    except (TypeError, ValueError):
                        return None
    return None


_PROPERTY_TYPE_MAP = {
    "SINGLE_FAMILY_HOME": PropertyKind.SINGLE_FAMILY,
    "CONDO": PropertyKind.CONDO,
    "TOWNHOUSE": PropertyKind.TOWNHOUSE,
    "MULTI_FAMILY": PropertyKind.MULTI_FAMILY,
    "MOBILE_MANUFACTURED": PropertyKind.MOBILE,
    "LOT_LAND": PropertyKind.LAND,
    "APARTMENT": PropertyKind.MULTI_FAMILY,
}

# "...has a lot size of 8712 sqft and was built in 1950." / "...lot size of
# 1.58 acres." -- the only place lot size + year built appear at all on some
# live rows (no structured lotSize field present on that same row).
_DESC_LOT_SQFT_RE = re.compile(r"lot size of ([\d,]+)\s*sqft", re.I)
_DESC_LOT_ACRES_RE = re.compile(r"lot size of ([\d.]+)\s*acres?", re.I)
_DESC_YEAR_BUILT_RE = re.compile(r"built in (\d{4})", re.I)


def _photo_gallery(media: dict) -> list[str]:
    """FOUND 2026-10-04: media.photos[] carries the REAL gallery (up to 24
    on a live-sampled row); the single heroImage previously kept is often a
    Google Street View static fallback when the listing has no real photos
    at all (confirmed live: heroImage pointed at maps.googleapis.com while
    media.photos was [] on that same row)."""
    photos = media.get("photos")
    out: list[str] = []
    if isinstance(photos, list):
        for p in photos:
            if not isinstance(p, dict):
                continue
            url_obj = p.get("url") or {}
            if not isinstance(url_obj, dict):
                continue
            url = url_obj.get("large") or url_obj.get("medium") or url_obj.get("small")
            if isinstance(url, str) and url.startswith("http"):
                out.append(url)
    return out


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
    # FOUND 2026-10-04: media.photos[] carries the REAL gallery; fall back
    # to the single heroImage (often a Google Street View static fallback
    # when the listing has no real photos) only when photos[] is empty.
    media = h.get("media") or {}
    photos = _photo_gallery(media) if isinstance(media, dict) else []
    if not photos:
        hero = (media.get("heroImage") or {}) if isinstance(media, dict) else {}
        url_obj = hero.get("url") or {}
        img_url = url_obj.get("medium") or url_obj.get("small") if isinstance(url_obj, dict) else None
        if isinstance(img_url, str) and img_url.startswith("http"):
            photos.append(img_url)
    # beds/baths/sqft — only price was captured before. Trulia's home object
    # carries these under bedrooms/bathrooms/floorSpace (shape varies).
    beds = _num_field(h.get("bedrooms"))
    baths = _num_field(h.get("bathrooms"))
    sqft = _num_field(h.get("floorSpace") or h.get("floorSpaceInSqFt"))
    # FOUND 2026-10-04: propertyType.value (e.g. "SINGLE_FAMILY_HOME",
    # "LOT_LAND") was never read -- property_kind was hardcoded UNKNOWN on
    # every row regardless.
    prop_type = ((h.get("propertyType") or {}).get("value") or "").strip().upper()
    kind = _PROPERTY_TYPE_MAP.get(prop_type, PropertyKind.UNKNOWN)
    # FOUND 2026-10-04: Trulia's own real description text, and the ONLY
    # place lot size + year built appear at all on some live rows (no
    # structured field for either). Promoted to first-class fields only
    # when a structured value isn't already present.
    desc_text = ((h.get("description") or {}).get("value") or "").strip()
    lot_sqft = None
    lot_m = _DESC_LOT_SQFT_RE.search(desc_text)
    if lot_m:
        try:
            lot_sqft = float(lot_m.group(1).replace(",", ""))
        except ValueError:
            lot_sqft = None
    if lot_sqft is None:
        acres_m = _DESC_LOT_ACRES_RE.search(desc_text)
        if acres_m:
            try:
                lot_sqft = float(acres_m.group(1)) * 43560.0
            except ValueError:
                lot_sqft = None
    year_built = None
    yb_m = _DESC_YEAR_BUILT_RE.search(desc_text)
    if yb_m:
        try:
            year_built = int(yb_m.group(1))
        except ValueError:
            year_built = None
    active_listing = h.get("activeListing") or {}
    provider = active_listing.get("provider") or {}
    agent_name = ((provider.get("listingAgent") or {}).get("name") or "").strip() or None
    broker_name = ((provider.get("broker") or {}).get("name") or "").strip() or None
    date_listed = active_listing.get("dateListed")
    return Listing(
        source=slug,
        source_url=f"https://www.trulia.com{href}" if href.startswith("/") else (href or URL),
        listing_type=_ltype_from_tags(h.get("fullTags") or h.get("tags")),
        property_kind=kind,
        state=state,
        city=(loc.get("city") or "").strip() or None,
        zip_code=(loc.get("zipCode") or "").strip() or None,
        street_address=addr_street,
        case_number=f"trulia-{home_id}" if home_id else None,
        latitude=coords.get("latitude") if isinstance(coords.get("latitude"), (int, float)) else None,
        longitude=coords.get("longitude") if isinstance(coords.get("longitude"), (int, float)) else None,
        opening_bid=price,
        bedrooms=beds,
        bathrooms=baths,
        living_sqft=sqft,
        lot_size_sqft=lot_sqft,
        year_built=year_built,
        description=desc_text or (
            f"Trulia foreclosure ({', '.join((t.get('formattedName') or '') for t in (h.get('fullTags') or []) if isinstance(t, dict)) or 'Foreclosure'})"
        ),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "trulia_id": home_id,
            "images": {"real": photos} if photos else {},
            # FOUND 2026-10-04: is_foreclosure/is_recently_sold/beds_raw/
            # baths_raw/floor_space_raw were all flat top-level raw keys
            # with no RAW_KEEP entry (only trulia_id/images were) --
            # silently dropped at every publish since this scraper was
            # built. Namespaced under a new registered "trulia" key; also
            # adds the new agent/broker/date_listed/property_type fields.
            "trulia": {
                "is_foreclosure": True,
                "is_recently_sold": status.get("isRecentlySold"),
                "beds_raw": h.get("bedrooms"),
                "baths_raw": h.get("bathrooms"),
                "floor_space_raw": h.get("floorSpace") or h.get("floorSpaceInSqFt"),
                "property_type": prop_type or None,
                "listing_agent": agent_name,
                "listing_broker": broker_name,
                "date_listed": date_listed,
            },
        },
    )


async def _fetch_page(url: str = URL) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []
    try:
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=False, timeout=90000,
            solve_cloudflare=False,
        )
    except Exception as exc:
        log.warning("trulia.fetch_failed", url=url, error=str(exc)[:200])
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
        listings: list[Listing] = []
        seen_ids: set[str] = set()
        for url in URL_VARIANTS:
            try:
                page_listings = await _fetch_page(url)
            except Exception as exc:
                log.warning("trulia.variant_failed", url=url, error=str(exc)[:160])
                continue
            for li in page_listings:
                # Dedupe by case_number (trulia-{home_id}) across URL variants
                key = li.case_number or li.street_address or ""
                if key and key in seen_ids:
                    continue
                if key:
                    seen_ids.add(key)
                listings.append(li)
            log.info("trulia.variant_done", url=url, found=len(page_listings),
                     total_unique=len(listings))
        log.info("trulia.done", total=len(listings))
        return listings
