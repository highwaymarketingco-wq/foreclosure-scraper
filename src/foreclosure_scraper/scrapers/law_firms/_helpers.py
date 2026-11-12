"""Shared helpers for parsing law firm trustee sale calendars."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...models import Listing, ListingType, PropertyKind

ADDR_RE = re.compile(
    r"(\d+\s+[A-Z][\w .'\-]+(?:Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|"
    r"Highway|Hwy|Boulevard|Blvd|Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy)\.?)",
    re.I,
)
COUNTY_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?)\s+County\b")
ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
STATE_RE = re.compile(r"\b(SC|NC)\b")
DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
    re.I,
)
CASE_RE = re.compile(r"\b\d{2,4}-?CP-?\d{2}-\d+|\b\d{2,4}-?SP-?\d{2}-\d+\b", re.I)
PARCEL_RE = re.compile(r"\b(?:parcel|tms|pin)\b[:#\s]+([A-Z0-9\-\.]+)", re.I)


def parse_listing_block(
    *,
    source_slug: str,
    source_url: str,
    text: str,
    state_hint: str | None = None,
    listing_type: ListingType = ListingType.FORECLOSURE_SALE,
) -> Listing | None:
    """Best-effort parse of a chunk of text describing one trustee sale."""
    if not text:
        return None
    addr_m = ADDR_RE.search(text)
    county_m = COUNTY_RE.search(text)
    zip_m = ZIP_RE.search(text)
    state_m = STATE_RE.search(text)
    date_m = DATE_RE.search(text)
    case_m = CASE_RE.search(text)
    parcel_m = PARCEL_RE.search(text)

    sale_date = None
    if date_m:
        try:
            sale_date = dateparser.parse(date_m.group(0))
        except (ValueError, TypeError):
            pass

    return Listing(
        source=source_slug,
        source_url=source_url,
        listing_type=listing_type,
        property_kind=PropertyKind.UNKNOWN,
        street_address=addr_m.group(1) if addr_m else None,
        county=county_m.group(1) if county_m else None,
        state=state_m.group(1) if state_m else state_hint,
        zip_code=zip_m.group(1) if zip_m else None,
        sale_date=sale_date,
        case_number=case_m.group(0) if case_m else None,
        parcel_id=parcel_m.group(1) if parcel_m else None,
        description=text[:500],
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )


def parse_blocks(text: str, *, source_slug: str, source_url: str) -> Iterable[Listing]:
    """Split a long page of trustee sales into per-property blocks and parse each."""
    # Heuristic: split on case-number markers or 'Date of Sale' / 'Sale Date' markers
    chunks = re.split(r"(?:Case No\.?:|Sale Date:|Date of Sale:|\n{2,}\s*\n)", text)
    out: list[Listing] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 50 or not ADDR_RE.search(chunk):
            continue
        li = parse_listing_block(
            source_slug=source_slug, source_url=source_url, text=chunk
        )
        if li:
            out.append(li)
    return out
