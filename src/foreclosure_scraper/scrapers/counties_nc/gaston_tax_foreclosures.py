"""Gaston County NC — Tax Foreclosures.

Gaston County publishes its tax-foreclosure auction properties as two
CivicPlus pages:

  * https://www.gastongov.com/669  — active / upcoming sales
  * https://www.gastongov.com/671  — previous sales (recent history, still
    useful motivated-seller leads: owner + parcel + address + upset status)

The county does NOT render these as an HTML <table>.  Each property is a
rich-text block inside the page's ``div.fr-view`` widget with labeled lines:

    Owner: Macie Clark
    Parcel: 103685
    Physical Address: 401 Pryor St., Gastonia, NC
    Sale Date: December 9, 2025 at 10 am.
    Current Bid: $87,240.23                (or "Starting Bid ...: $4,000.00")
    Minimum of Next Upset Bid: $91,602.24
    Last Day to Upset: March 16, 2026
    File Number: 25 M 388
    Sale Closed-Property Sold              (status line)

Records are delimited by the "Owner:" marker.  We split on that, then pull
each field by its label.  The active page is frequently empty (off-season) —
that is expected and simply yields 0 rows from /669 while /671 still returns
history.

Free, public, no login.
Slug: counties_nc.gaston_tax_foreclosures
Category: county_tax
ListingType: TAX_SALE  (foreclosure_process="tax")
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

ACTIVE_URL = "https://www.gastongov.com/669"
PREVIOUS_URL = "https://www.gastongov.com/671"

# City name -> best-effort ZIP hints omitted on purpose: the page gives city in
# the "Physical Address" line, which we keep whole in street_address for dedupe.

# label -> (regex capturing the value after the label on its line)
_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
_DATE_RE = re.compile(
    rf"((?:{_MONTHS})\s+\d{{1,2}},?\s+\d{{4}})", re.I
)


def _money(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "").strip()
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _label(block: str, label: str) -> str | None:
    """Return the text on the line that starts with ``label`` (after the colon)."""
    for line in block.splitlines():
        line = line.strip()
        if line.lower().startswith(label.lower()):
            val = line.split(":", 1)[1].strip() if ":" in line else ""
            return val or None
    return None


def _widget_text(html: str) -> str | None:
    """Extract the newline-joined visible text of the page's fr-view widget."""
    if not html or len(html) < 200:
        return None
    tree = HTMLParser(html)
    node = tree.css_first("div.fr-view")
    if node is None:
        # Fallback: whole body text still contains the labeled lines.
        node = tree.body
    if node is None:
        return None
    return node.text(separator="\n")


def _records(text: str) -> list[str]:
    """Split the widget text into per-property blocks on the 'Owner:' marker."""
    if not text:
        return []
    # Normalize whitespace but keep line breaks.
    lines = [l.strip() for l in text.splitlines()]
    blocks: list[list[str]] = []
    cur: list[str] | None = None
    for l in lines:
        if re.match(r"^Owner\s*:", l, re.I):
            if cur:
                blocks.append(cur)
            cur = [l]
        elif cur is not None:
            cur.append(l)
    if cur:
        blocks.append(cur)
    # A valid record needs at least an Owner plus one of parcel/address/file.
    out = []
    for b in blocks:
        joined = "\n".join(b)
        if re.search(r"Parcel\s*:|Physical Address\s*:|File Number\s*:", joined, re.I):
            out.append(joined)
    return out


def _status_line(block: str) -> str | None:
    """The auction status is the free line right after the File Number line."""
    lines = [l.strip() for l in block.splitlines() if l.strip()]
    for i, l in enumerate(lines):
        if re.match(r"^File Number\s*:", l, re.I):
            if i + 1 < len(lines):
                nxt = lines[i + 1]
                # Only treat as status if it isn't another labeled field.
                if not re.match(
                    r"^(Owner|Parcel|Physical Address|Sale Date|Current Bid|"
                    r"Starting Bid|Minimum|Last Day)\s*:",
                    nxt,
                    re.I,
                ):
                    return nxt
    return None


def _parse_block(block: str, source_url: str) -> Listing | None:
    owner = _label(block, "Owner")
    parcel = _label(block, "Parcel")
    address = _label(block, "Physical Address")
    sale_date_raw = _label(block, "Sale Date")
    current_bid_raw = _label(block, "Current Bid")
    starting_bid_raw = _label(block, "Starting Bid") or _label(
        block, "Starting Bid (Subject to Change)"
    )
    upset_min_raw = _label(block, "Minimum of Next Upset Bid")
    last_upset_raw = _label(block, "Last Day to Upset")
    file_number = _label(block, "File Number")
    status = _status_line(block)

    # Must have at least one strong identifier.
    if not (parcel or address or file_number):
        return None

    opening_bid = _money(current_bid_raw) or _money(starting_bid_raw) or _money(
        upset_min_raw
    )
    sale_date = _parse_date(sale_date_raw)
    upset_deadline = _parse_date(last_upset_raw)

    # City best-effort: last comma-part before a trailing ", NC".
    city = None
    if address:
        parts = [p.strip() for p in address.split(",") if p.strip()]
        # e.g. "401 Pryor St." , "Gastonia" , "NC"
        if len(parts) >= 2 and parts[-1].upper() in ("NC", "N.C.", "NORTH CAROLINA"):
            city = parts[-2]
        elif len(parts) >= 2:
            city = parts[-1]

    desc_bits = [b for b in (
        f"Owner: {owner}" if owner else None,
        f"Sale: {sale_date_raw}" if sale_date_raw else None,
        current_bid_raw and f"Current Bid: {current_bid_raw}",
        upset_min_raw and f"Min Upset: {upset_min_raw}",
        status,
    ) if b]

    return Listing(
        source="counties_nc.gaston_tax_foreclosures",
        source_url=source_url,
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.UNKNOWN,
        foreclosure_process="tax",
        state="NC",
        county="Gaston",
        parcel_id=parcel,
        street_address=address,
        city=city,
        defendant=owner,
        owner_name=owner,
        opening_bid=opening_bid,
        sale_date=sale_date,
        upset_bid_deadline=upset_deadline,
        auction_status=status,
        case_number=file_number,
        description=" | ".join(desc_bits) if desc_bits else None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"gaston_tax_foreclosures": {
            "owner": owner,
            "parcel": parcel,
            "physical_address": address,
            "sale_date": sale_date_raw,
            "current_bid": current_bid_raw,
            "starting_bid": starting_bid_raw,
            "min_next_upset_bid": upset_min_raw,
            "last_day_to_upset": last_upset_raw,
            "file_number": file_number,
            "status": status,
        }},
    )


class GastonTaxForeclosures(BaseScraper):
    slug = "counties_nc.gaston_tax_foreclosures"
    name = "Gaston County NC Tax Foreclosures"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[str] = set()

        for url in (ACTIVE_URL, PREVIOUS_URL):
            try:
                html = await get_text(url, impersonate=True, timeout=40.0)
            except Exception as exc:  # noqa: BLE001 - never raise from a scraper
                log.warning(
                    "gaston_tax_foreclosures.fetch_fail",
                    url=url,
                    error=str(exc)[:160],
                )
                continue

            try:
                text = _widget_text(html or "")
                if not text:
                    continue
                for block in _records(text):
                    li = _parse_block(block, url)
                    if li is None:
                        continue
                    key = li.dedupe_key()
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(li)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "gaston_tax_foreclosures.parse_fail",
                    url=url,
                    error=str(exc)[:160],
                )
                continue

        log.info("gaston_tax_foreclosures.done", count=len(out))
        return out
