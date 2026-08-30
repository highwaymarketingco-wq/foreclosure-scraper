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
import time
from datetime import datetime
from typing import Iterable

import structlog
from curl_cffi import requests as cf
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# Sleep between requests to avoid rate-limiting (foreclosure.com returns 429)
REQUEST_DELAY = 0.5  # seconds between page fetches

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


def _fetch_search(state: str, url: str, slug_name: str, pages_cap: int = 100) -> list[Listing]:
    """Fetch all listings from a search-view URL."""
    out: list[Listing] = []
    seen_ids: set[str] = set()

    try:
        r = cf.get(url, impersonate="chrome", timeout=15)
    except Exception as exc:
        log.warning("foreclosure_dot_com.search_failed", url=url, error=str(exc)[:200])
        return out

    if r.status_code != 200 or len(r.text) < 5000:
        return out

    total = _get_total(r.text)
    listings = _extract_search_listings(r.text, state, slug_name)
    for li in listings:
        key = li.case_number or li.source_url
        if key not in seen_ids:
            seen_ids.add(key)
            out.append(li)

    total_pages = min(pages_cap, (total + 9) // 10) if total > 0 else 1
    for page in range(2, total_pages + 1):
        time.sleep(REQUEST_DELAY)
        try:
            r = cf.get(f"{url}&pg={page}", impersonate="chrome", timeout=15)
        except Exception:
            break
        if r.status_code != 200 or len(r.text) < 5000 or "Too Many Requests" in r.text:
            break
        listings = _extract_search_listings(r.text, state, slug_name)
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


def _fetch_city(state: str, url: str, slug_name: str, pages_cap: int = 50) -> list[Listing]:
    """Fetch all listings from a city/zip URL (JSON-LD path)."""
    out: list[Listing] = []
    seen_ids: set[str] = set()

    try:
        r = cf.get(url, impersonate="chrome", timeout=15)
    except Exception as exc:
        log.warning("foreclosure_dot_com.city_failed", url=url, error=str(exc)[:200])
        return out

    if r.status_code != 200 or len(r.text) < 5000:
        return out

    total = _get_total(r.text)
    listings = _extract_jsonld_listings(r.text, state, slug_name)
    for li in listings:
        key = li.case_number or li.source_url
        if key not in seen_ids:
            seen_ids.add(key)
            out.append(li)

    total_pages = min(pages_cap, (total + 9) // 10) if total > 0 else 1
    for page in range(2, total_pages + 1):
        time.sleep(REQUEST_DELAY)
        try:
            r = cf.get(f"{url}?pg={page}", impersonate="chrome", timeout=15)
        except Exception:
            break
        if r.status_code != 200 or len(r.text) < 5000 or "Too Many Requests" in r.text:
            break
        listings = _extract_jsonld_listings(r.text, state, slug_name)
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
        # Step 1: Search view (broadest coverage)
        by_id: dict[str, Listing] = {}
        for state, url in SEARCH_URLS:
            try:
                listings = _fetch_search(state, url, self.slug)
                for li in listings:
                    key = li.case_number or li.source_url
                    if key not in by_id:
                        by_id[key] = li
            except Exception as exc:
                log.warning("foreclosure_dot_com.search_error", state=state, error=str(exc)[:200])

        # Step 2: City pages (richer detail — beds/baths/sqft/lat/lon)
        # Merge by ID: city data overrides search data
        for state, url in CITY_URLS:
            time.sleep(REQUEST_DELAY)
            try:
                listings = _fetch_city(state, url, self.slug)
                for li in listings:
                    key = li.case_number or li.source_url
                    if key in by_id:
                        # Merge: city data has richer detail, keep it
                        by_id[key] = li
                    else:
                        by_id[key] = li
            except Exception as exc:
                log.warning("foreclosure_dot_com.city_error", url=url, error=str(exc)[:200])

        out = list(by_id.values())
        log.info("foreclosure_dot_com.done", total=len(out),
                 nc=sum(1 for l in out if l.state == "NC"),
                 sc=sum(1 for l in out if l.state == "SC"))
        return out
