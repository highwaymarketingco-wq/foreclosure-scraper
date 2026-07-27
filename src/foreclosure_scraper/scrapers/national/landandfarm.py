"""LandAndFarm.com land listings for NC + SC core counties.

LandAndFarm is part of the Land.com network alongside LandWatch and Land.com.
Like LandWatch, it is Akamai-protected and requires Scrapling StealthyFetcher.
The page structure is identical: JSON-LD CollectionPage → ItemList with
RealEstateListing items containing name, address, price, and agent contact info.

URL pattern: /search/{state}/{county}-county-land-for-sale/
Robots.txt (archived): User-agent: * Allow: /  (GPTBot disallowed only).
25 listings per page; paginated with ?page=N.
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

MAX_PAGES = 10

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
    urls = []
    for county, state in _COUNTY_TO_STATE.items():
        state_slug = "north-carolina" if state == "NC" else "south-carolina"
        url = f"https://www.landandfarm.com/search/{state_slug}/{county}-county-land-for-sale/"
        urls.append((county, state, url))
    return urls


_ACRES_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:acres?|ac\.?)", re.I)


def _extract_acres(name: str, desc: str | None) -> float | None:
    text = f"{name} {desc or ''}"
    m = _ACRES_RE.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except (ValueError, TypeError):
            pass
    return None


def _extract_listing_id(url: str) -> str | None:
    m = re.search(r"/property/[^/]*-(\d+)/?", url)
    return m.group(1) if m else None


def _extract_county(url: str, name: str) -> str | None:
    m = re.search(r"/([a-z]+)-county-", url, re.I)
    if m:
        return m.group(1).title()
    m = re.search(r",\s*([A-Z][a-z]+)\s+County", name)
    if m:
        return m.group(1)
    return None


def _extract_listings(html: str, slug: str) -> list[Listing]:
    out: list[Listing] = []
    tree = HTMLParser(html)

    for script_node in tree.css("script"):
        text = script_node.text()
        if not text or len(text) < 5000:
            continue
        if "mainEntity" not in text or "itemListElement" not in text:
            continue
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
        break
    return out


def _parse_item(item: dict, slug: str) -> Listing | None:
    url = (item.get("url") or "").strip()
    if not url:
        return None
    name = (item.get("name") or "").strip()
    desc = (item.get("description") or "").strip() or None

    place = item.get("contentLocation") or {}
    addr = place.get("address") or {}
    street = (addr.get("streetAddress") or "").strip() or None
    city = (addr.get("addressLocality") or "").strip() or None
    state = (addr.get("addressRegion") or "").strip().upper() or None
    if state and len(state) > 2:
        state = state[:2]
    zip_code = (str(addr.get("postalCode") or "").strip())[:5] or None

    offers = item.get("offers") or {}
    price = offers.get("price")
    if isinstance(price, str):
        try:
            price = float(price.replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            price = None
    elif not isinstance(price, (int, float)):
        price = None

    offered_by = offers.get("offeredBy") or {}
    agent_name = (offered_by.get("name") or "").strip() or None
    agent_phone = (offered_by.get("telephone") or "").strip() or None
    brokerage = ((offered_by.get("worksFor") or {}).get("name") or "").strip() or None

    image = (item.get("image") or "").strip() or None
    photos = [image] if image and image.startswith("http") else []

    acreage = _extract_acres(name, desc)
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
            "landandfarm": {
                "title": name,
                "agent_name": agent_name,
                "agent_phone": agent_phone,
                "brokerage": brokerage,
                "listing_id": _extract_listing_id(url),
            },
            "images": {"real": photos} if photos else {},
        },
    )


async def _fetch_county(
    county: str, state: str, base_url: str, slug: str
) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("landandfarm.scrapling_missing")
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
                "landandfarm.fetch_fail",
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
            "landandfarm.page_done",
            county=county,
            page=page,
            found=len(listings),
            new=new,
        )
    return out


class LandAndFarm(BaseScraper):
    slug = "national.landandfarm"
    name = "LandAndFarm.com (NC + SC land listings)"
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
                    "landandfarm.county_failed",
                    county=county,
                    error=str(exc)[:200],
                )
                continue
            for li in rows:
                if li.source_url not in seen:
                    seen.add(li.source_url)
                    out.append(li)
            log.info(
                "landandfarm.county_done", county=county, count=len(rows)
            )
        log.info("landandfarm.done", total=len(out))
        return out