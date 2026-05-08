"""Kania Law Firm — NC tax foreclosure auctions across western NC counties.

The Kania Law Firm (Asheville, NC; kanialawfirm.com) handles tax-foreclosure
sales for 20+ NC counties — the largest single source of tax-sale listings
in the western half of the state. Their /tax-foreclosures/ section
publishes a daily-updated list of upcoming auctions with parcel,
opening bid, county, and sale date.

Site sits behind Cloudflare; plain httpx returns 503. We try the static
fetch first (sometimes Cloudflare lets us through) and fall back to
Scrapling stealth when blocked.

Sale-detail pages on Kania typically include:
  - County (in the URL slug or page title)
  - Parcel ID (PIN)
  - Sale date + time
  - Sale location (county courthouse)
  - Opening bid ($)
  - Property address (when available)
  - Defendant / record owner

Output: ListingType.TAX_SALE so downstream tax-sale enrichments fire
(parcel→address backfill via county GIS, etc).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Optional

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind
from ._helpers import (
    ADDR_RE,
    COUNTY_RE,
    DATE_RE,
    PARCEL_RE,
    ZIP_RE,
    parse_blocks,
)


# Kania publishes both an index and a dedicated sales page. We sweep the
# sales page (more complete) and fall back to the index.
INDEX_URLS = (
    "https://kanialawfirm.com/tax-foreclosures/tax-foreclosure-sales/",
    "https://kanialawfirm.com/tax-foreclosures/foreclosure-listings/",
    "https://kanialawfirm.com/tax-foreclosures/foreclosures/",
)

# Western-NC counties Kania has historically represented. Used as a
# fallback parser when the page text doesn't include "X County" but does
# include the county name on its own line (common in their layouts).
KNOWN_KANIA_COUNTIES = (
    "Avery", "Buncombe", "Burke", "Caldwell", "Cherokee", "Clay",
    "Cleveland", "Gaston", "Graham", "Haywood", "Henderson", "Jackson",
    "Lincoln", "Macon", "Madison", "Mcdowell", "Mitchell", "Polk",
    "Rutherford", "Swain", "Transylvania", "Watauga", "Yancey",
    "Mecklenburg",
)

# Opening bid: "$12,345.67" or "Minimum bid: $X" / "Opening bid: $X"
BID_RE = re.compile(
    r"(?:opening|minimum|starting)?\s*bid[:\s]*\$\s*([\d,]+(?:\.\d{2})?)",
    re.I,
)
# Bare $ amount fallback (Kania often lists bid as a plain dollar value
# in a table cell)
BARE_BID_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
# Tax foreclosure case numbers — NC pattern is "YY-CVS-NNN" or "YY SP NNN"
KANIA_CASE_RE = re.compile(r"\b(\d{2,4}[\s\-]?(?:CVS|SP|CV)[\s\-]?\d+)\b", re.I)


def _flatten(text: str) -> str:
    """Collapse whitespace + decode common entities."""
    text = re.sub(r"&(?:nbsp|amp|lt|gt|times);", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _county_from_text(text: str) -> Optional[str]:
    """Pull a Kania-county name out of a chunk of listing text."""
    m = COUNTY_RE.search(text)
    if m:
        c = m.group(1).strip()
        # Filter "Cherokee Indian" or non-NC counties via known list
        for known in KNOWN_KANIA_COUNTIES:
            if c.lower() == known.lower():
                return known
        return c
    # Fallback: scan for known-county tokens directly
    for known in KNOWN_KANIA_COUNTIES:
        if re.search(rf"\b{re.escape(known)}\b", text, re.I):
            return known
    return None


def _parse_table_row(row, source_url: str, slug: str) -> Optional[Listing]:
    """Try to parse a <tr> as a single tax-foreclosure listing.

    Kania's typical table columns (vary by tenant): County | Sale Date |
    Parcel | Address | Opening Bid | Case#.
    """
    cells = row.css("td")
    if len(cells) < 3:
        return None
    cell_texts = [_flatten(c.text()) for c in cells]
    blob = " | ".join(cell_texts)
    if not blob or len(blob) < 10:
        return None

    # Identify the "row" by needing AT LEAST a parcel/case# OR an address
    addr_m = ADDR_RE.search(blob)
    parcel_m = PARCEL_RE.search(blob)
    case_m = KANIA_CASE_RE.search(blob)
    if not (addr_m or parcel_m or case_m):
        return None

    sale_date = None
    date_m = DATE_RE.search(blob)
    if date_m:
        try:
            from dateutil import parser as dateparser
            sale_date = dateparser.parse(date_m.group(0))
        except (ValueError, TypeError):
            pass

    bid = None
    bid_m = BID_RE.search(blob) or BARE_BID_RE.search(blob)
    if bid_m:
        try:
            bid = float(bid_m.group(1).replace(",", ""))
        except ValueError:
            pass
        # Sanity: tax-sale opening bids are typically $500-$500K. Reject
        # anything outside [$10, $5M] to skip stray dollar values.
        if bid is not None and (bid < 10 or bid > 5_000_000):
            bid = None

    # Detail link if present
    detail = source_url
    a = row.css_first("a[href]")
    if a:
        href = a.attributes.get("href") or ""
        if href.startswith("/"):
            detail = f"https://kanialawfirm.com{href}"
        elif href.startswith("http"):
            detail = href

    zip_m = ZIP_RE.search(blob)

    return Listing(
        source=slug,
        source_url=detail,
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=_county_from_text(blob),
        street_address=addr_m.group(1) if addr_m else None,
        zip_code=zip_m.group(1) if zip_m else None,
        parcel_id=parcel_m.group(1) if parcel_m else None,
        sale_date=sale_date,
        case_number=case_m.group(1).strip() if case_m else None,
        opening_bid=bid,
        description=blob[:500],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"kania": {"row_text": blob[:500]}},
    )


def _parse_html(html: str, source_url: str, slug: str) -> list[Listing]:
    """Try table-row parsing first; fall back to text-block parsing."""
    out: list[Listing] = []
    seen_keys: set[str] = set()
    if not html or len(html) < 200:
        return out

    tree = HTMLParser(html)

    # Path A: table rows (most common Kania layout)
    for table in tree.css("table"):
        for row in table.css("tr"):
            li = _parse_table_row(row, source_url, slug)
            if li:
                key = (li.parcel_id or "") + "|" + (li.case_number or "") + "|" + (li.street_address or "")
                if key.strip("|") and key not in seen_keys:
                    seen_keys.add(key)
                    out.append(li)

    if out:
        return out

    # Path B: text-block parsing (handles non-table layouts — Kania sometimes
    # uses card/list views on different sub-pages)
    body = tree.body
    if body:
        text = body.text(separator="\n")
        for li in parse_blocks(text, source_slug=slug, source_url=source_url):
            # Force NC + TAX_SALE since this is the Kania scope
            li.state = "NC"
            li.listing_type = ListingType.TAX_SALE
            if not li.county:
                li.county = _county_from_text(li.description or "")
            key = (li.parcel_id or "") + "|" + (li.case_number or "") + "|" + (li.street_address or "")
            if key.strip("|") and key not in seen_keys:
                seen_keys.add(key)
                out.append(li)

    return out


async def _fetch_with_fallback(url: str) -> Optional[str]:
    """Try plain httpx; on 5xx fall back to Scrapling stealth."""
    try:
        return await get_text(url, timeout=30.0)
    except Exception:
        pass
    # Cloudflare-protected — need full browser. StealthyFetcher routes
    # through camoufox so it gets past Cloudflare's JS challenge.
    try:
        from scrapling.fetchers import StealthyFetcher
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=60000,
        )
        body = getattr(result, "body", b"")
        if isinstance(body, (bytes, bytearray)):
            return body.decode("utf-8", errors="replace")
        return str(body or "")
    except Exception:
        return None


class KaniaLawFirm(BaseScraper):
    slug = "law_firms.kania"
    name = "Kania Law Firm (NC tax foreclosures)"
    category = "law_firm"
    expected_min_count = 1
    timeout_s = 240.0
    # Cloudflare in front; static HTTP often 503s. requires_render=True
    # makes the run summary tag this as RENDER-REQUIRED rather than
    # REGRESSED on partial failure.
    requires_render = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_keys: set[str] = set()
        for url in INDEX_URLS:
            html = await _fetch_with_fallback(url)
            if not html:
                continue
            for li in _parse_html(html, url, self.slug):
                key = (
                    (li.parcel_id or "")
                    + "|"
                    + (li.case_number or "")
                    + "|"
                    + (li.street_address or "")
                    + "|"
                    + (li.county or "")
                )
                if key.strip("|") and key not in seen_keys:
                    seen_keys.add(key)
                    out.append(li)
        return out
