"""IRS Treasury auction scraper — seized real property sales.

Source: https://www.irsauctions.gov/auction/items
Each listing links to /ad/<slug> detail pages with address, minimum bid, etc.

As of 2026-08-20: 18 active auctions, 0 in NC/SC. Scraper will catch new ones
dynamically when they appear.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from curl_cffi import requests as cf
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE_URL = "https://www.irsauctions.gov"
ITEMS_URL = f"{BASE_URL}/auction/items"
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

# State -> county mapping
NC_CITIES = {
    "charlotte": "Mecklenburg", "raleigh": "Wake", "asheville": "Buncombe",
    "wilmington": "New Hanover", "fayetteville": "Cumberland",
    "greensboro": "Guilford", "durham": "Durham", "winston": "Forsyth",
}
SC_CITIES = {
    "spartanburg": "Spartanburg", "greenville": "Greenville",
    "columbia": "Richland", "charleston": "Charleston",
    "anderson": "Anderson", "florence": "Florence", "aiken": "Aiken",
}


def _extract_state(text: str) -> str | None:
    """Try to find a US state abbreviation in text."""
    states = [
        "NC", "SC", "VA", "GA", "TN", "FL", "AL", "MS", "LA", "AR",
        "TX", "OK", "NM", "AZ", "CA", "OR", "WA", "CO", "NY", "PA",
        "OH", "IL", "IN", "MI", "WI", "MN", "IA", "MO", "KY", "WV",
        "MD", "DE", "NJ", "CT", "RI", "MA", "VT", "NH", "ME", "MT",
        "ID", "WY", "UT", "NV", "HI", "AK", "ND", "SD", "NE", "KS",
    ]
    for s in states:
        m = re.search(r'\b' + s + r'\b', text)
        if m:
            return s
    # Also check state names
    state_names = {
        "North Carolina": "NC", "South Carolina": "SC", "Virginia": "VA",
        "Georgia": "GA", "Tennessee": "TN", "Florida": "FL",
    }
    for name, abbr in state_names.items():
        if name.lower() in text.lower():
            return abbr
    return None


def _extract_city(text: str, state: str) -> str | None:
    """Try to extract city before state."""
    m = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*' + state, text)
    if m:
        return m.group(1).strip()
    return None


async def _fetch_irs() -> list[Listing]:
    out: list[Listing] = []
    try:
        r = cf.get(ITEMS_URL, impersonate="chrome", timeout=15, headers=HEADERS)
    except Exception as exc:
        log.warning("irs.fetch_fail", error=str(exc)[:200])
        return out

    if r.status_code != 200 or len(r.text) < 1000:
        log.warning("irs.bad_response", status=r.status_code, size=len(r.text))
        return out

    tree = HTMLParser(r.text)

    # Find property listing links — each /ad/<slug>
    ad_links = set()
    for node in tree.css("a[href^='/ad/']"):
        href = node.attributes.get("href", "")
        if href and href != "/ad/":
            ad_links.add(href)

    log.info("irs.found_ads", count=len(ad_links))

    for ad_path in ad_links:
        ad_url = BASE_URL + ad_path
        try:
            ar = cf.get(ad_url, impersonate="chrome", timeout=15, headers=HEADERS)
        except Exception:
            continue

        if ar.status_code != 200:
            continue

        atree = HTMLParser(ar.text)

        # Extract all text content to find state
        full_text = atree.body.text() if atree.body else ar.text
        state = _extract_state(full_text)
        if not state:
            continue

        # Filter NC + SC only
        if state not in ("NC", "SC"):
            continue

        city = _extract_city(full_text, state)
        county = None
        if state == "NC" and city:
            county = NC_CITIES.get(city.lower())
        elif state == "SC" and city:
            county = SC_CITIES.get(city.lower())

        # Try to find address
        addr_m = re.search(
            r'\b\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+'
            r'(?:St|Ave|Dr|Rd|Blvd|Ln|Way|Ct|Cir|Hwy|Pkwy)\b',
            full_text,
        )
        street = addr_m.group(0) if addr_m else None

        # Try to find minimum bid
        bid_m = re.search(r'\$(\d{1,3}(?:,\d{3})+)', full_text)
        min_bid = int(bid_m.group(1).replace(",", "")) if bid_m else None

        # Title from page
        title_node = atree.css_first("h1")
        title = title_node.text().strip() if title_node else ad_path

        out.append(Listing(
            source="national.irs_treasury",
            source_url=ad_url,
            listing_type=ListingType.AUCTION,
            property_kind=PropertyKind.UNKNOWN,
            state=state,
            county=county,
            street_address=street,
            city=city,
            zip_code=None,
            opening_bid=min_bid,
            description=title,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"irs_treasury": {
                "url": ad_url,
                "title": title,
                "min_bid": min_bid,
            }},
        ))

    log.info("irs.parse_done", total=len(out))
    return out


class IRSTreasuryAuctions(BaseScraper):
    slug = "national.irs_treasury"
    name = "IRS Treasury Seized Property Auctions"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        return await _fetch_irs()
