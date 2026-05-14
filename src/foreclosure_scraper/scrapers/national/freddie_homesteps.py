"""Freddie Mac HomeSteps REO inventory.

The /listing/search page is a Drupal-rendered page — no JS required for
the results list. Listings appear inline as `.views-row` blocks. As of
2026-05-14 the nationwide inventory is empty ("No results found" on the
unfiltered all-states search). When inventory comes back this scraper
will pick it up; until then it cleanly returns 0 in under a second per
state.
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
    ("NC", "https://www.homesteps.com/listing/search?state=NC"),
    ("SC", "https://www.homesteps.com/listing/search?state=SC"),
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


def _parse_row(row, state: str) -> Listing | None:
    """Parse a single .views-row card. Returns None for any unparseable row
    (no address)."""
    addr_node = row.css_first("[class*='address'], .field--name-field-address")
    if addr_node is None:
        text = row.text(separator=" ", strip=True)
        # try inline regex on the whole card text
        m = _ADDR_RE.search(text)
        if not m:
            return None
        street, city, st, z = m.group(1).strip(), m.group(2).strip(), m.group(3), m.group(4)
    else:
        addr = addr_node.text(strip=True)
        m = _ADDR_RE.match(addr)
        if not m:
            return None
        street, city, st, z = m.group(1).strip(), m.group(2).strip(), m.group(3), m.group(4)
    if st != state:
        return None

    price_node = row.css_first("[class*='price']")
    price = None
    if price_node is not None:
        pm = _PRICE_RE.search(price_node.text(strip=True))
        if pm:
            try:
                price = float(pm.group(1).replace(",", ""))
            except ValueError:
                price = None

    kind_node = row.css_first("[class*='type'], [class*='property-type']")
    kind_text = kind_node.text(strip=True) if kind_node is not None else None

    link_node = row.css_first("a[href*='/listing/']") or row.css_first("a[href]")
    link = (link_node.attributes.get("href", "") if link_node else "") or "https://www.homesteps.com/"
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
        description=f"Freddie Mac HomeSteps REO. {kind_text or ''}".strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"homesteps_kind": kind_text},
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
    if "no-results" in r.text or "No results found" in r.text:
        return []
    tree = HTMLParser(r.text)
    out: list[Listing] = []
    for row in tree.css(".views-row, [class*='property-listing'] article, [class*='listing-tile']"):
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
