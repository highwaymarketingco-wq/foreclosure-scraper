"""LandsofAmerica.com (now Land.com) land listings for NC + SC core counties.

LandsofAmerica.com redirects to Land.com — both are part of the Land.com
network alongside LandWatch and LandAndFarm. The site is behind Akamai with
a behavioral challenge (sensor data collection) that is harder to bypass
than LandWatch/LandAndFarm. Scrapling StealthyFetcher is attempted first;
if the Akamai challenge blocks it, the scraper will return BLOCKED via
safe_run's classification.

URL pattern: /{County}-County-{ST}/all-land/
Robots.txt (archived): User-agent: * Allow: /  (GPTBot disallowed only).

The JSON-LD page structure is identical to LandWatch/LandAndFarm when the
challenge is bypassed: CollectionPage → ItemList → RealEstateListing.
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

# County name → (state, URL-safe county slug for Land.com pattern)
# Land.com uses Title-Case-County-ST pattern: /Buncombe-County-NC/all-land/
NC_COUNTIES = [
    "Buncombe", "Henderson", "Cleveland", "Gaston", "Rutherford", "Polk",
    "Transylvania", "McDowell", "Lincoln", "Mitchell", "Burke", "Brunswick",
    "Pender", "Onslow", "Carteret", "Dare",
]
SC_COUNTIES = [
    "Spartanburg", "Anderson", "Pickens", "Oconee", "Cherokee", "Union",
    "Laurens", "Charleston", "Georgetown", "Horry",
]

_COUNTY_TO_STATE: dict[str, str] = {}
for c in NC_COUNTIES:
    _COUNTY_TO_STATE[c] = "NC"
for c in SC_COUNTIES:
    _COUNTY_TO_STATE[c] = "SC"


def _build_urls() -> list[tuple[str, str, str]]:
    urls = []
    for county, state in _COUNTY_TO_STATE.items():
        url = f"https://www.land.com/{county}-County-{state}/all-land/"
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
    if m:
        return m.group(1)
    m = re.search(r"/pid/(\d+)", url)
    return m.group(1) if m else None


def _is_akamai_challenge(html: str) -> bool:
    """Detect Akamai behavioral challenge page."""
    indicators = [
        "scf-akamai",
        "sec-if-cpt-container",
        "behavioral-content",
        "akamai",
        "Access Denied",
    ]
    lower = html.lower()
    return any(ind.lower() in lower for ind in indicators) and len(html) < 10000


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
    # Normalize land.com URLs to https
    if url.startswith("/"):
        url = f"https://www.land.com{url}"

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

    # County from URL: /{County}-County-{ST}/...
    m = re.search(r"/([A-Za-z]+)-County-", url)
    county = m.group(1) if m else None

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
            "landsofamerica": {
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
        log.warning("landsofamerica.scrapling_missing")
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}?page={page}"
        try:
            # Land.com has a harder Akamai challenge — try with network_idle
            # to give the sensor script time to resolve.
            result = await StealthyFetcher.async_fetch(
                url,
                headless=True,
                network_idle=True,
                timeout=90000,
                solve_cloudflare=False,
            )
        except Exception as exc:
            log.warning(
                "landsofamerica.fetch_fail",
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
        # Detect Akamai challenge page
        if _is_akamai_challenge(html):
            log.warning(
                "landsofamerica.akamai_challenge",
                county=county,
                page=page,
                html_len=len(html),
            )
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
            "landsofamerica.page_done",
            county=county,
            page=page,
            found=len(listings),
            new=new,
        )
    return out


class LandsOfAmerica(BaseScraper):
    slug = "national.landsofamerica"
    name = "LandsofAmerica.com / Land.com (NC + SC land listings)"
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
                    "landsofamerica.county_failed",
                    county=county,
                    error=str(exc)[:200],
                )
                continue
            for li in rows:
                if li.source_url not in seen:
                    seen.add(li.source_url)
                    out.append(li)
            log.info(
                "landsofamerica.county_done", county=county, count=len(rows)
            )
        log.info("landsofamerica.done", total=len(out))
        return out