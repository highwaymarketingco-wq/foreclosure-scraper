"""Freddie Mac HomeSteps REO inventory.

The /listing/search page is server-rendered — no JS required for the
results list. The real filter is the free-text `?search=` param (the old
`?state=` param is ignored and returns the full nationwide list), so we
query `?search=NC` and `?search=SC`. Each result is a `div.property-teaser`
card wrapped in an `a[href^="/listingdetails/"]` anchor, with address,
price and beds/baths/sqft in `.property-address`, `.property-price` and
`.property-details`.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

URLS = (
    ("NC", "https://www.homesteps.com/listing/search?search=NC"),
    ("SC", "https://www.homesteps.com/listing/search?search=SC"),
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
}

_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
_NUM_RE = re.compile(r"([\d,]+)")
_ADDR_RE = re.compile(r"^(.+?),\s*([A-Za-z .'-]+),\s*([A-Z]{2})\s*(\d{5})?")


def _kind(label: str | None) -> PropertyKind:
    if not label:
        return PropertyKind.UNKNOWN
    s = label.lower()
    if "single" in s or "detached" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "multi" in s or "duplex" in s:
        return PropertyKind.MULTI_FAMILY
    if "manufactured" in s or "mobile" in s:
        return PropertyKind.MOBILE
    if "land" in s:
        return PropertyKind.LAND
    return PropertyKind.UNKNOWN


def _wrapping_href(row) -> str | None:
    """Find the /listingdetails/ href for a card — either on the wrapping
    anchor (the card is nested inside <a>) or on an anchor inside the card."""
    inner = row.css_first("a.no-decoration[href^='/listingdetails/']") or row.css_first(
        "a[href^='/listingdetails/']"
    )
    if inner is not None:
        return inner.attributes.get("href")
    node = row.parent
    depth = 0
    while node is not None and depth < 5:
        if node.tag == "a":
            href = node.attributes.get("href")
            if href and "/listingdetails/" in href:
                return href
        node = node.parent
        depth += 1
    return None


def _parse_row(row, state: str) -> Listing | None:
    """Parse a single property-teaser card. Returns None for any unparseable
    row (no address)."""
    addr_node = row.css_first(
        "div.property-address, [class*='address'], .field--name-field-address"
    )
    if addr_node is None:
        addr = row.text(separator=" ", strip=True)
    else:
        addr = addr_node.text(separator=" ", strip=True)
    # The markup puts street/city/state/zip on separate lines, so collapse all
    # whitespace (incl. newlines) to single spaces BEFORE the address regex.
    addr = re.sub(r"\s+", " ", addr or "").strip()
    m = _ADDR_RE.search(addr)
    if not m:
        return None
    street, city, st, z = m.group(1).strip(), m.group(2).strip(), m.group(3), m.group(4)
    if st != state:
        return None

    price_node = row.css_first("div.property-price, [class*='price']")
    price = None
    if price_node is not None:
        pm = _PRICE_RE.search(price_node.text(strip=True))
        if pm:
            try:
                price = float(pm.group(1).replace(",", ""))
            except ValueError:
                price = None

    details_node = row.css_first("div.property-details")
    details_text = (
        re.sub(r"\s+", " ", details_node.text()).strip()
        if details_node is not None
        else None
    )

    kind_node = row.css_first("[class*='type'], [class*='property-type']")
    kind_text = kind_node.text(strip=True) if kind_node is not None else None

    link = _wrapping_href(row) or "https://www.homesteps.com/"
    if link and not link.startswith("http"):
        link = f"https://www.homesteps.com{link}"

    return Listing(
        source="national.freddie_homesteps",
        source_url=link,
        listing_type=ListingType.REO,
        property_kind=_kind(kind_text),
        state=st,
        city=city,
        zip_code=z,
        street_address=street,
        opening_bid=price,
        description=" ".join(
            p for p in ("Freddie Mac HomeSteps REO.", kind_text, details_text) if p
        ).strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"homesteps_kind": kind_text, "homesteps_details": details_text},
    )


async def _fetch_state(state: str, url: str) -> list[Listing]:
    async with client(timeout=30.0) as c:
        try:
            r = await c.get(url, headers=HEADERS, follow_redirects=True)
        except Exception as exc:
            log.warning("freddie.fetch_failed", state=state, error=str(exc)[:200])
            return []
    if r.status_code != 200 or len(r.text) < 5000:
        return []
    tree = HTMLParser(r.text)
    out: list[Listing] = []
    cards = tree.css("div.property-teaser") or tree.css(
        ".views-row, [class*='property-listing'] article, [class*='listing-tile']"
    )
    # Only honor a "no results" short-circuit when there are genuinely no cards
    # — the phrase can appear in inert page chrome even when results exist.
    if not cards and ("No results found" in r.text or "no-results" in r.text):
        return []
    for row in cards:
        try:
            li = _parse_row(row, state)
        except Exception:
            continue
        if li is not None:
            out.append(li)
    return out


class FreddieHomeSteps(BaseScraper):
    slug = "national.freddie_homesteps"
    name = "Freddie Mac HomeSteps (REO)"
    category = "national_reo"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state, url in URLS:
            try:
                listings = await _fetch_state(state, url)
                out.extend(listings)
                log.info("freddie.state_done", state=state, count=len(listings))
            except Exception as exc:
                log.warning("freddie.state_failed", state=state, error=str(exc)[:200])
        return out
