"""Shared helper for NC tax-foreclosure scrapers.

Each NC county tax department publishes upcoming foreclosure sales on
its own page with a different HTML layout. The common shape is a
table-of-rows where each row has: owner, parcel, description,
clerk file #, opening bid. Sale date+location appear once for the batch.

This helper does the generic parse; per-county subclasses provide URL,
table selector hints, and county name.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...http_client import client
from ...models import Listing, ListingType, PropertyKind


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

_DATE_RE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4}"
    r"(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))?)",
    re.I,
)
_LOCATION_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+,\s*[A-Z][\w .'\-]+,?\s*NC[\w\s]*)", re.I,
)
_BID_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


def _parse_sale_date(html: str) -> tuple[datetime | None, str | None]:
    sale_date = None
    sale_location = None
    m = _DATE_RE.search(html)
    if m:
        try:
            sale_date = dateparser.parse(m.group(1), fuzzy=True)
        except (ValueError, TypeError):
            sale_date = None
    loc = _LOCATION_RE.search(html)
    if loc:
        sale_location = loc.group(1).strip()
    return sale_date, sale_location


def _parse_money(s: str) -> float | None:
    if not s:
        return None
    m = _BID_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


async def fetch_county_tax_listings(
    *,
    slug: str,
    county: str,
    url: str,
    table_selector: str = "table tr",
    expected_columns: int = 5,
    column_layout: str = "owner_parcel_desc_file_bid",
) -> list[Listing]:
    """Fetch the county tax-foreclosure HTML and parse into Listings.

    column_layout values:
      "owner_parcel_desc_file_bid"  — Henderson / Wake / most counties
      "parcel_owner_desc_file_bid"  — some counties swap col 1+2
    """
    async with client(timeout=25.0) as c:
        try:
            r = await c.get(url, headers=HEADERS)
        except Exception:
            return []
        if r.status_code != 200:
            return []
        html = r.text

    if not html or len(html) < 500:
        return []

    sale_date, sale_location = _parse_sale_date(html)
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()

    for row in tree.css(table_selector):
        cells = row.css("th") or row.css("td")
        if len(cells) < expected_columns:
            continue

        if column_layout == "parcel_owner_desc_file_bid":
            parcel = (cells[0].text() or "").strip()
            owner = (cells[1].text() or "").strip()
            description = (cells[2].text() or "").strip()
            file_no = (cells[3].text() or "").strip()
            bid_str = (cells[4].text() or "").strip()
        else:  # owner_parcel_desc_file_bid (default)
            owner = (cells[0].text() or "").strip()
            parcel = (cells[1].text() or "").strip()
            description = (cells[2].text() or "").strip()
            file_no = (cells[3].text() or "").strip()
            bid_str = (cells[4].text() or "").strip()

        if not parcel or parcel.lower() in {"parcel #", "parcel", "parcel id", "pin"}:
            continue
        # Allow alphanumeric parcels (some counties use letters);
        # require at least 4 chars, at least one digit somewhere.
        if len(parcel) < 4 or not re.search(r"\d", parcel):
            continue

        key = (file_no or parcel).strip()
        if key in seen:
            continue
        seen.add(key)

        out.append(Listing(
            source=slug,
            source_url=url,
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county=county,
            parcel_id=parcel,
            sale_date=sale_date,
            sale_location=sale_location,
            opening_bid=_parse_money(bid_str),
            defendant=owner or None,
            case_number=file_no or None,
            description=description[:500] or None,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={county.lower() + "_tax": {
                "owner": owner, "description": description, "bid_str": bid_str,
            }},
        ))
    return out
