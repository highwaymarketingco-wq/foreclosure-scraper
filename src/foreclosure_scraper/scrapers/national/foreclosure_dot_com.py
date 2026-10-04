"""Foreclosure.com — public preview scrape via curl-cffi browser impersonation.

Two access paths discovered 2026-08-20:

1. SEARCH VIEW (broadest coverage):
   /listing/search?q=South%20Carolina&pa=100000&view=list  (793 SC listings)
   /listing/search?q=North%20Carolina&pa=100000&view=list (435 NC listings)
   HTML row format with address slug, listing ID, price, property type.
   10 listings/page, paginated with ?pg=N.

2. CITY/ZIP PAGES (richest detail):
   /listings/spartanburg-sc-29302/  (JSON-LD with beds/baths/sqft/lat/lon)
   /listings/charlotte-nc/  (JSON-LD)
   10 listings/page, paginated with ?pg=N.

Street NUMBERS are masked ("Moore Dr" instead of "1234 Moore Dr") but city,
state, ZIP, lat/lng, beds/baths/sqft, and the listing ID are all present.

Strategy: scrape BOTH paths. Search view for total coverage (~1,228 NC/SC
listings), city pages for enriched detail (beds/baths/sqft/lat/lon). Merge
by listing ID. When a listing appears in both, the city-page data wins.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text_impersonate
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# Search-view URLs (broadest coverage)
SEARCH_URLS = (
    ("NC", "https://www.foreclosure.com/listing/search?q=North%20Carolina&pa=100000&view=list"),
    ("SC", "https://www.foreclosure.com/listing/search?q=South%20Carolina&pa=100000&view=list"),
)

# City/zip-level URLs (richest detail via JSON-LD)
CITY_URLS = (
    # NC
    ("NC", "https://www.foreclosure.com/listings/charlotte-nc/"),
    ("NC", "https://www.foreclosure.com/listings/raleigh-nc/"),
    ("NC", "https://www.foreclosure.com/listings/wilmington-nc/"),
    ("NC", "https://www.foreclosure.com/listings/winston-salem-nc/"),
    ("NC", "https://www.foreclosure.com/listings/greenville-nc/"),
    ("NC", "https://www.foreclosure.com/listings/shelby-nc/"),
    ("NC", "https://www.foreclosure.com/listings/asheville-nc-28801/"),
    ("NC", "https://www.foreclosure.com/listings/hendersonville-nc-28792/"),
    ("NC", "https://www.foreclosure.com/listings/buncombe-county-nc/"),
    ("NC", "https://www.foreclosure.com/listings/haywood-nc/"),
    # SC
    ("SC", "https://www.foreclosure.com/listings/anderson-sc/"),
    ("SC", "https://www.foreclosure.com/listings/berkeley-county-sc-29461/"),
    ("SC", "https://www.foreclosure.com/listings/blythewood-sc/"),
    ("SC", "https://www.foreclosure.com/listings/boiling-springs-sc/"),
    ("SC", "https://www.foreclosure.com/listings/columbia-sc/"),
    ("SC", "https://www.foreclosure.com/listings/cowpens-sc/"),
    ("SC", "https://www.foreclosure.com/listings/dorchester-county-sc-29485/"),
    ("SC", "https://www.foreclosure.com/listings/florence-sc/"),
    ("SC", "https://www.foreclosure.com/listings/inman-sc/"),
    ("SC", "https://www.foreclosure.com/listings/richland-county-sc-29016/"),
    ("SC", "https://www.foreclosure.com/listings/richland-county-sc-29203/"),
    ("SC", "https://www.foreclosure.com/listings/richland-county-sc-29229/"),
    ("SC", "https://www.foreclosure.com/listings/rock-hill-sc/"),
    ("SC", "https://www.foreclosure.com/listings/roebuck-sc/"),
    ("SC", "https://www.foreclosure.com/listings/spartanburg-sc-29301/"),
    ("SC", "https://www.foreclosure.com/listings/spartanburg-sc-29302/"),
    ("SC", "https://www.foreclosure.com/listings/spartanburg-sc-29303/"),
    ("SC", "https://www.foreclosure.com/listings/spartanburg-sc-29306/"),
    ("SC", "https://www.foreclosure.com/listings/spartanburg-sc-29307/"),
    ("SC", "https://www.foreclosure.com/listings/pickens-sc-29671/"),
    ("SC", "https://www.foreclosure.com/listings/laurens-sc/"),
    ("SC", "https://www.foreclosure.com/listings/union-sc/"),
    ("SC", "https://www.foreclosure.com/listings/newberry-sc/"),
    ("SC", "https://www.foreclosure.com/listings/greenwood-sc/"),
    ("SC", "https://www.foreclosure.com/listings/abbeville-sc/"),
)

JSONLD_RE = re.compile(
    r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>",
    re.S | re.I,
)
LID_RE = re.compile(r"/(\d+)_lid\b")
TOTAL_RE = re.compile(r"(\d+)\s+Foreclosure Listings", re.I)
SLUG_RE = re.compile(r"/address/([^/]+)/(\d+)_lid")


def _slug_to_address(slug: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Parse a URL slug like 'Bob-Bo-Link-Ct-Ladson-SC-29456' into parts."""
    parts = slug.split("-")
    # Find the state (2-char uppercase after a city segment)
    state_idx = None
    for i, p in enumerate(parts):
        if p.upper() in ("NC", "SC", "GA", "VA", "TN", "FL", "AL", "KY", "WV", "MD", "DC"):
            state_idx = i
            break
    if state_idx is None:
        return None, None, None, None
    state = parts[state_idx].upper()
    # ZIP is the segment after state (if numeric)
    zip_code = None
    city_end = state_idx
    if state_idx + 1 < len(parts) and parts[state_idx + 1].isdigit():
        zip_code = parts[state_idx + 1]
        city_end = state_idx
    # City is between street and state
    city = " ".join(parts[len(parts) - city_end:state_idx]) if state_idx > 0 else None
    # Simplified: street is everything before city
    # This is imprecise but we have lat/lon from JSON-LD as the real locator
    street = " ".join(parts[:state_idx - len(parts) + state_idx]) if state_idx > 0 else None
    return street, city, state, zip_code


def _parse_search_row(html_chunk: str, state: str, slug_name: str) -> Listing | None:
    """Parse a single listing row from the search-view HTML."""
    addr_m = SLUG_RE.search(html_chunk)
    if not addr_m:
        return None
    slug = addr_m.group(1)
    listing_id = addr_m.group(2)

    # Extract alt text for address
    alt_m = re.search(r'alt="View this home at ([^"]+)"', html_chunk)
    alt_text = alt_m.group(1) if alt_m else slug.replace("-", " ")

    # Parse address from the slug: "Bob-Bo-Link-Ct-Ladson-SC-29456"
    street_city, city, state_code, zip_code = _slug_to_address(slug)
    display = alt_text or slug.replace("-", " ")
    if street_city is None:
        street_city = display

    # Extract price
    price_m = re.search(r"\$([\d,]+)", html_chunk)
    price = None
    if price_m:
        try:
            price = int(price_m.group(1).replace(",", ""))
        except ValueError:
            pass

    # Extract property type
    prop_type = "Single-Family" if "Single-Family" in html_chunk else None

    # Extract photo URL
    img_m = re.search(r'src="(//[^"]+listingphoto[^"]+)"', html_chunk)
    photo = "https:" + img_m.group(1) if img_m else None

    return Listing(
        source=slug_name,
        source_url=f"https://www.foreclosure.com/address/{slug}/{listing_id}_lid",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY if prop_type == "Single-Family" else PropertyKind.UNKNOWN,
        state=state,
        city=city,
        zip_code=zip_code,
        street_address=street_city,
        case_number=f"fc-{listing_id}",
        description=alt_text,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "fc_listing_id": listing_id,
            "fc_price_emv": price,
            "anonymized_address": True,
            "fc_search_view": True,
            "images": {"real": [photo]} if photo else {},
        },
    )


def _parse_jsonld_node(node: dict, state: str, slug_name: str) -> Listing | None:
    """Parse a JSON-LD RealEstateListing node."""
    item = node.get("item") if isinstance(node, dict) else None
    if not isinstance(item, dict) or item.get("@type") != "RealEstateListing":
        return None
    url = item.get("url") or ""
    lid_match = LID_RE.search(url)
    listing_id = lid_match.group(1) if lid_match else None
    img = item.get("image") or ""
    if isinstance(img, str) and img.startswith("//"):
        img = "https:" + img
    photos = [img] if isinstance(img, str) and img.startswith("http") else []
    offered = (item.get("offers") or {}).get("itemOffered") or {}
    addr = offered.get("address") or {}
    region = (addr.get("addressRegion") or "").strip().upper()
    if region != state:
        return None
    street = (addr.get("streetAddress") or "").strip() or None
    city = (addr.get("addressLocality") or "").strip() or None
    zip_code = (addr.get("postalCode") or "").strip() or None
    geo = offered.get("geo") or {}
    lat = geo.get("latitude")
    lng = geo.get("longitude")
    beds = offered.get("numberOfBedrooms")
    baths = offered.get("numberOfBathroomsTotal")
    floor = offered.get("floorSize") or {}
    sqft = None
    if floor.get("unitCode", "").upper() == "SQFT":
        try:
            sqft = int(floor.get("value"))
        except (TypeError, ValueError):
            sqft = None

    return Listing(
        source=slug_name,
        source_url=url,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY
        if offered.get("@type") == "SingleFamilyResidence"
        else PropertyKind.UNKNOWN,
        state=region,
        city=city,
        zip_code=zip_code,
        street_address=street,
        case_number=f"fc-{listing_id}" if listing_id else None,
        latitude=lat if isinstance(lat, (int, float)) else None,
        longitude=lng if isinstance(lng, (int, float)) else None,
        description=item.get("name") or f"Foreclosure.com listing {listing_id}",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "fc_listing_id": listing_id,
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "anonymized_address": True,
            "fc_city_page": True,
            "images": {"real": photos} if photos else {},
        },
    )


def _extract_jsonld_listings(html: str, state: str, slug_name: str) -> list[Listing]:
    """Extract listings from JSON-LD on city/zip pages."""
    out: list[Listing] = []
    for m in JSONLD_RE.finditer(html):
        body = m.group(1).strip()
        if not body:
            continue
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        graph = data.get("@graph", []) if isinstance(data, dict) else []
        for cp in graph:
            if not isinstance(cp, dict) or cp.get("@type") != "CollectionPage":
                continue
            item_list = (cp.get("mainEntity") or {}).get("itemListElement") or []
            for node in item_list:
                li = _parse_jsonld_node(node, state, slug_name)
                if li is not None:
                    out.append(li)
    return out


def _extract_search_listings(html: str, state: str, slug_name: str) -> list[Listing]:
    """Extract listings from search-view HTML rows."""
    out: list[Listing] = []
    # Split by listing row container
    rows = re.split(r"clone_\d+", html)
    for chunk in rows[1:]:
        li = _parse_search_row(chunk, state, slug_name)
        if li is not None:
            out.append(li)
    return out


def _get_total(html: str) -> int:
    """Get total listing count from page title."""
    title_m = re.search(r"<title>(.*?)</title>", html, re.S)
    if title_m:
        total_m = TOTAL_RE.search(title_m.group(1))
        if total_m:
            return int(total_m.group(1))
    return 0


async def _fetch_search(state: str, url: str, slug_name: str, pages_cap: int = 100) -> list[Listing]:
    """Fetch all listings from a search-view URL.

    REWRITTEN 2026-10-04 (national.* extraction-completeness audit, batch
    16) to go through the shared `http_client.get_text_impersonate()`
    instead of calling `curl_cffi.requests.get()` (a bare sync client)
    directly. This is not a style change -- it fixes a real, severe,
    long-silent bug: this host has been returning a hard 403 ("Sorry,
    access to this resource is restricted... VPN or proxy") to EVERY
    search/city URL since ~2026-08-29 (live-reproduced 2026-10-04 across
    multiple impersonation profiles), yet the raw `cf.get()` call's
    `r.status_code != 200` check just silently `return`ed an empty list on
    every page -- `safe_run()` then saw a clean empty result with no
    exception and no recorded block, so every run since has logged
    `OUTCOME_ZERO` ("ran clean but returned 0 rows") instead of
    `OUTCOME_BLOCKED`, identical in shape to the already-fixed
    `law_firms.ingle_firm` TLS-swallow bug. Confirmed via the run logs:
    5,483 real rows on 2026-08-27, then 0 on EVERY run from 2026-08-29
    through 2026-09-25 (the most recent before this audit) with nobody
    the wiser. `get_text_impersonate()` is the one fetch path in this
    codebase that both honors the per-host politeness throttle AND records
    a block signal `base_scraper.safe_run()` reads to correctly promote a
    swallowed-exception zero-result run to BLOCKED (see http_client.py's
    module docstring + `_block_holder`) -- raw `curl_cffi.requests` bypasses
    that entirely. Also drops the manual `time.sleep(REQUEST_DELAY)`
    pacing between pages: the shared transport already paces same-host
    requests (`_throttle()`), so a second, redundant sleep on top of it
    only slowed real runs down for no benefit.
    """
    out: list[Listing] = []
    seen_ids: set[str] = set()

    try:
        html = await get_text_impersonate(url, timeout=15.0)
    except Exception as exc:
        log.warning("foreclosure_dot_com.search_failed", url=url, error=str(exc)[:200])
        return out

    if len(html) < 5000:
        return out

    total = _get_total(html)
    listings = _extract_search_listings(html, state, slug_name)
    for li in listings:
        key = li.case_number or li.source_url
        if key not in seen_ids:
            seen_ids.add(key)
            out.append(li)

    total_pages = min(pages_cap, (total + 9) // 10) if total > 0 else 1
    for page in range(2, total_pages + 1):
        try:
            html = await get_text_impersonate(f"{url}&pg={page}", timeout=15.0)
        except Exception as exc:
            log.warning("foreclosure_dot_com.search_page_failed", url=url, page=page,
                        error=str(exc)[:200])
            break
        if len(html) < 5000 or "Too Many Requests" in html:
            break
        listings = _extract_search_listings(html, state, slug_name)
        new_count = 0
        for li in listings:
            key = li.case_number or li.source_url
            if key not in seen_ids:
                seen_ids.add(key)
                out.append(li)
                new_count += 1
        if new_count == 0:
            break

    log.info("foreclosure_dot_com.search_done", state=state, count=len(out), total=total)
    return out


async def _fetch_city(state: str, url: str, slug_name: str, pages_cap: int = 50) -> list[Listing]:
    """Fetch all listings from a city/zip URL (JSON-LD path). See
    `_fetch_search`'s docstring for why this goes through
    `get_text_impersonate()` rather than raw `curl_cffi.requests`."""
    out: list[Listing] = []
    seen_ids: set[str] = set()

    try:
        html = await get_text_impersonate(url, timeout=15.0)
    except Exception as exc:
        log.warning("foreclosure_dot_com.city_failed", url=url, error=str(exc)[:200])
        return out

    if len(html) < 5000:
        return out

    total = _get_total(html)
    listings = _extract_jsonld_listings(html, state, slug_name)
    for li in listings:
        key = li.case_number or li.source_url
        if key not in seen_ids:
            seen_ids.add(key)
            out.append(li)

    total_pages = min(pages_cap, (total + 9) // 10) if total > 0 else 1
    for page in range(2, total_pages + 1):
        try:
            html = await get_text_impersonate(f"{url}?pg={page}", timeout=15.0)
        except Exception as exc:
            log.warning("foreclosure_dot_com.city_page_failed", url=url, page=page,
                        error=str(exc)[:200])
            break
        if len(html) < 5000 or "Too Many Requests" in html:
            break
        listings = _extract_jsonld_listings(html, state, slug_name)
        new_count = 0
        for li in listings:
            key = li.case_number or li.source_url
            if key not in seen_ids:
                seen_ids.add(key)
                out.append(li)
                new_count += 1
        if new_count == 0:
            break

    area = url.split("/listings/")[-1].rstrip("/")
    log.info("foreclosure_dot_com.city_done", area=area, state=state, count=len(out), total=total)
    return out


class ForeclosureDotCom(BaseScraper):
    slug = "national.foreclosure_dot_com"
    name = "Foreclosure.com (public preview, anonymized addresses)"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 900.0  # 15 min for full search + city pagination

    async def fetch(self) -> Iterable[Listing]:
        # REWRITTEN 2026-10-04 (see _fetch_search's docstring for the full
        # rationale): this used to run a fully-synchronous body
        # (`_fetch_sync`) on a worker thread via `asyncio.to_thread` because
        # `curl_cffi.requests.get()` blocks and the old pagination loop used
        # `time.sleep()`. Now that `_fetch_search`/`_fetch_city` are native
        # coroutines awaiting `get_text_impersonate()` at every page fetch,
        # the event loop stays free on its own -- no thread hop needed, AND
        # (the actually severe part) a block/403 is now correctly recorded
        # for `safe_run()`'s ZERO->BLOCKED promotion instead of silently
        # swallowed by a bare `status_code != 200` check.
        by_id: dict[str, Listing] = {}
        for state, url in SEARCH_URLS:
            try:
                listings = await _fetch_search(state, url, self.slug)
                for li in listings:
                    key = li.case_number or li.source_url
                    if key not in by_id:
                        by_id[key] = li
            except Exception as exc:
                log.warning("foreclosure_dot_com.search_error", state=state, error=str(exc)[:200])

        # City pages (richer detail — beds/baths/sqft/lat/lon). Merge by ID:
        # city data overrides search data. No manual inter-URL sleep here —
        # get_text_impersonate() already paces same-host requests.
        for state, url in CITY_URLS:
            try:
                listings = await _fetch_city(state, url, self.slug)
                for li in listings:
                    key = li.case_number or li.source_url
                    by_id[key] = li
            except Exception as exc:
                log.warning("foreclosure_dot_com.city_error", url=url, error=str(exc)[:200])

        out = list(by_id.values())
        log.info("foreclosure_dot_com.done", total=len(out),
                 nc=sum(1 for l in out if l.state == "NC"),
                 sc=sum(1 for l in out if l.state == "SC"))
        return out
