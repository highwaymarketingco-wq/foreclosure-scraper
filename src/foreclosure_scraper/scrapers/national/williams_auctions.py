"""Williams & Williams auction scraper.

Homepage has JSON-LD ItemList with upcoming auctions. Sitemap has 49 pages
but none in NC/SC footprint as of 2026-08-20. Scraper checks dynamically.

URLs with NC/SC properties have historically appeared — the scraper will
catch them if they show up.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable

import structlog
from curl_cffi import requests as cf

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE_URL = "https://www.williamsauction.com"
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

# State -> county mapping for known NC/SC cities
NC_CITIES = {
    "charlotte": "Mecklenburg",
    "raleigh": "Wake",
    "asheville": "Buncombe",
    "wilmington": "New Hanover",
    "fayetteville": "Cumberland",
    "greensboro": "Guilford",
    "winston-salem": "Forsyth",
    "durham": "Durham",
    "winston": "Forsyth",
    "greenville": "Pitt",
}
SC_CITIES = {
    "spartanburg": "Spartanburg",
    "greenville": "Greenville",
    "columbia": "Richland",
    "charleston": "Charleston",
    "anderson": "Anderson",
    "florence": "Florence",
    "sumter": "Sumter",
    "aiken": "Aiken",
    "myrtle beach": "Horry",
    "rock hill": "York",
}


def _extract_jsonld(html: str) -> list[dict]:
    """Extract all JSON-LD blocks from HTML."""
    blocks = re.findall(
        r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
        html, re.S,
    )
    out = []
    for b in blocks:
        try:
            data = json.loads(b.strip())
            if isinstance(data, list):
                out.extend(data)
            elif isinstance(data, dict):
                out.append(data)
        except Exception:
            pass
    return out


def _parse_address_from_title(title: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Try to extract city/state/zip from an auction title like
    'Court-Ordered Auction in Sand Springs, OK - August 2026'."""
    m = re.search(r"in\s+([^,]+),\s*([A-Z]{2})\b", title)
    if m:
        city = m.group(1).strip()
        state = m.group(2)
        return None, city, state, None
    return None, None, None, None


async def _fetch_williams() -> list[Listing]:
    out: list[Listing] = []
    try:
        r = cf.get(BASE_URL + "/", impersonate="chrome", timeout=15, headers=HEADERS)
    except Exception as exc:
        log.warning("williams.fetch_fail", error=str(exc)[:200])
        return out

    if r.status_code != 200 or len(r.text) < 5000:
        log.warning("williams.bad_response", status=r.status_code, size=len(r.text))
        return out

    # Parse JSON-LD ItemList
    blocks = _extract_jsonld(r.text)
    for block in blocks:
        if block.get("@type") != "ItemList":
            continue
        items = block.get("itemListElement", [])
        for item in items:
            name = item.get("name", item.get("item", {}).get("name", ""))
            url = item.get("url", item.get("item", {}).get("url", ""))
            if not name:
                continue

            street, city, state, zip_code = _parse_address_from_title(name)
            if not state:
                continue
            state = state.upper()
            if state not in ("NC", "SC"):
                continue

            county = None
            if state == "NC" and city:
                county = NC_CITIES.get(city.lower())
            elif state == "SC" and city:
                county = SC_CITIES.get(city.lower())

            full_url = url if url.startswith("http") else BASE_URL + url if url else BASE_URL

            out.append(Listing(
                source="national.williams",
                source_url=full_url,
                listing_type=ListingType.AUCTION,
                property_kind=PropertyKind.UNKNOWN,
                state=state,
                county=county,
                street_address=street,
                city=city,
                zip_code=zip_code,
                description=name,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"williams": {"title": name, "url": full_url}},
            ))

    # Also check sitemap for new NC/SC landing pages
    try:
        sm = cf.get(BASE_URL + "/pages-sitemap.xml", impersonate="chrome", timeout=15, headers=HEADERS)
        if sm.status_code == 200:
            urls = re.findall(r"<loc>(.*?)</loc>", sm.text)
            for u in urls:
                # Check if URL contains NC/SC city names
                lower = u.lower()
                found_city = None
                found_state = None
                for city, county in NC_CITIES.items():
                    if city.replace(" ", "") in lower or city in lower:
                        found_city = city
                        found_state = "NC"
                        found_county = county
                        break
                if not found_city:
                    for city, county in SC_CITIES.items():
                        if city.replace(" ", "") in lower or city in lower:
                            found_city = city
                            found_state = "SC"
                            found_county = county
                            break
                if found_city:
                    out.append(Listing(
                        source="national.williams",
                        source_url=u,
                        listing_type=ListingType.AUCTION,
                        property_kind=PropertyKind.UNKNOWN,
                        state=found_state or "",
                        county=found_county,
                        city=found_city.title(),
                        description=f"Williams auction landing page: {u}",
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"williams": {"url": u, "from_sitemap": True}},
                    ))
    except Exception:
        pass

    log.info("williams.parse_done", total=len(out))
    return out


class WilliamsAuctions(BaseScraper):
    slug = "national.williams"
    name = "Williams & Williams Auctions"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 30.0

    async def fetch(self) -> Iterable[Listing]:
        return await _fetch_williams()
