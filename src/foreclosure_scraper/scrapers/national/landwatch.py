"""LandWatch.com land listings for NC + SC core counties.

LandWatch is part of the Land.com network (LandWatch, LandAndFarm, Land.com).
All three sites are behind Akamai WAF — plain httpx gets 403. Scrapling's
StealthyFetcher bypasses the gate and returns full HTML with embedded JSON-LD
structured data (schema.org CollectionPage → ItemList → RealEstateListing).

Each listing item contains:
  name, description, url, image,
  contentLocation.address.{streetAddress, addressLocality, addressRegion, postalCode},
  offers.{price, priceCurrency, offeredBy.{name, telephone, worksFor.name}}

Robots.txt (archived): User-agent: * Allow: /  (GPTBot disallowed only).
25 listings per page; we paginate up to MAX_PAGES per county.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

MAX_PAGES = 10  # safety cap; most counties have 2-5 pages

# Core counties — NC (16) + SC (10)
NC_COUNTIES = [
    "buncombe", "henderson", "cleveland", "gaston", "rutherford", "polk",
    "transylvania", "mcdowell", "lincoln", "mitchell", "burke", "brunswick",
    "pender", "onslow", "carteret", "dare",
]
SC_COUNTIES = [
    "spartanburg", "anderson", "pickens", "oconee", "cherokee", "union",
    "laurens", "charleston", "georgetown", "horry",
]

_COUNTY_TO_STATE: dict[str, str] = {}
for c in NC_COUNTIES:
    _COUNTY_TO_STATE[c] = "NC"
for c in SC_COUNTIES:
    _COUNTY_TO_STATE[c] = "SC"


def _build_urls() -> list[tuple[str, str, str]]:
    """Returns list of (county_slug, state, search_url)."""
    urls = []
    for county, state in _COUNTY_TO_STATE.items():
        state_slug = "north-carolina" if state == "NC" else "south-carolina"
        url = f"https://www.landwatch.com/{state_slug}-land-for-sale/{county}-county"
        urls.append((county, state, url))
    return urls


def _extract_listings(html: str, slug: str) -> list[Listing]:
    """Parse JSON-LD CollectionPage → ItemList from LandWatch HTML."""
    out: list[Listing] = []
    tree = HTMLParser(html)

    # The JSON-LD is in a <script> tag (not always type=application/ld+json
    # on LandWatch — sometimes it's a plain script). Find the big one with
    # mainEntity / itemListElement.
    for script_node in tree.css("script"):
        text = script_node.text()
        if not text or len(text) < 5000:
            continue
        if "mainEntity" not in text or "itemListElement" not in text:
            continue
        # Extract the JSON object
        start = text.find("{")
        if start < 0:
            continue
        depth = 0
        end = start
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            if depth == 0:
                end = i + 1
                break
        try:
            data = json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            continue
        me = data.get("mainEntity") or {}
        items = me.get("itemListElement") or []
        if not isinstance(items, list):
            continue
        for entry in items:
            if not isinstance(entry, dict):
                continue
            item = entry.get("item") or {}
            li = _parse_item(item, slug)
            if li:
                out.append(li)
        break  # only one CollectionPage script per page
    return out


def _parse_item(item: dict, slug: str) -> Listing | None:
    url = (item.get("url") or "").strip()
    if not url:
        return None
    name = (item.get("name") or "").strip()
    desc = (item.get("description") or "").strip() or None

    # Address
    place = item.get("contentLocation") or {}
    addr = place.get("address") or {}
    street = (addr.get("streetAddress") or "").strip() or None
    city = (addr.get("addressLocality") or "").strip() or None
    state = (addr.get("addressRegion") or "").strip().upper() or None
    if state and len(state) > 2:
        state = state[:2]
    zip_code = (str(addr.get("postalCode") or "").strip())[:5] or None

    # Price
    offers = item.get("offers") or {}
    price = offers.get("price")
    if isinstance(price, str):
        try:
            price = float(price.replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            price = None
    elif not isinstance(price, (int, float)):
        price = None

    # Contact info
    offered_by = offers.get("offeredBy") or {}
    agent_name = (offered_by.get("name") or "").strip() or None
    agent_phone = (offered_by.get("telephone") or "").strip() or None
    brokerage = ((offered_by.get("worksFor") or {}).get("name") or "").strip() or None

    # Image
    image = (item.get("image") or "").strip() or None
    photos = [image] if image and image.startswith("http") else []

    # Extract acreage from name or description
    acreage = _extract_acres(name, desc)

    # County from URL or name
    county = _extract_county(url, name)

    return Listing(
        source=slug,
        source_url=url,
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.LAND,
        street_address=street,
        city=city,
        state=state,
        zip_code=zip_code,
        county=county,
        opening_bid=float(price) if price else None,
        acreage=acreage,
        description=(desc or name)[:500],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "landwatch": {
                "title": name,
                "agent_name": agent_name,
                "agent_phone": agent_phone,
                "brokerage": brokerage,
                "listing_id": _extract_pid(url),
            },
            "images": {"real": photos} if photos else {},
        },
    )


_ACRES_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:acres?|ac\.?)", re.I)
_PID_RE = re.compile(r"/pid/(\d+)")


def _extract_acres(name: str, desc: str | None) -> float | None:
    text = f"{name} {desc or ''}"
    m = _ACRES_RE.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except (ValueError, TypeError):
            pass
    return None


def _extract_pid(url: str) -> str | None:
    m = _PID_RE.search(url)
    return m.group(1) if m else None


def _extract_county(url: str, name: str) -> str | None:
    # URL pattern: /{county}-county-{state}-...-for-sale/pid/...
    m = re.search(r"/([a-z]+)-county-", url, re.I)
    if m:
        return m.group(1).title()
    # Try from name: "Fairview, Buncombe County, NC ..."
    m = re.search(r",\s*([A-Z][a-z]+)\s+County", name)
    if m:
        return m.group(1)
    return None


async def _fetch_county(
    county: str, state: str, base_url: str, slug: str
) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("landwatch.scrapling_missing")
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}?page={page}"
        try:
            result = await StealthyFetcher.async_fetch(
                url,
                headless=True,
                network_idle=False,
                timeout=60000,
                solve_cloudflare=False,
            )
        except Exception as exc:
            log.warning(
                "landwatch.fetch_fail",
                county=county,
                page=page,
                error=str(exc)[:200],
            )
            break
        body = getattr(result, "body", b"")
        html = (
            body.decode("utf-8", errors="replace")
            if isinstance(body, bytes)
            else str(body or "")
        )
        if not html or len(html) < 5000:
            break
        listings = _extract_listings(html, slug)
        if not listings:
            break
        new = 0
        for li in listings:
            if li.source_url not in seen:
                seen.add(li.source_url)
                out.append(li)
                new += 1
        if new == 0:
            break
        log.info(
            "landwatch.page_done",
            county=county,
            page=page,
            found=len(listings),
            new=new,
        )
    return out


class LandWatch(BaseScraper):
    slug = "national.landwatch"
    name = "LandWatch.com (NC + SC land listings)"
    category = "national_land_listing"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()
        for county, state, url in _build_urls():
            try:
                rows = await _fetch_county(county, state, url, self.slug)
            except Exception as exc:
                log.warning(
                    "landwatch.county_failed",
                    county=county,
                    error=str(exc)[:200],
                )
                continue
            for li in rows:
                if li.source_url not in seen:
                    seen.add(li.source_url)
                    out.append(li)
            log.info(
                "landwatch.county_done", county=county, count=len(rows)
            )
        log.info("landwatch.done", total=len(out))
        return out