"""Shared helper for NC tax-foreclosure scrapers.

Each NC county tax department publishes upcoming foreclosure sales on
its own page with a different HTML layout. The common shape used to be
a table-of-rows, but most counties have moved to free-form paragraphs
inside Drupal/SharePoint accordions. Wake, Forsyth, Guilford, Durham,
and New Hanover all use a per-listing paragraph format like:

    Tax ID#: 0047741   Amount due: $16,988.90
    Property Address: 619 Cumberland St., Raleigh
    Date of First Action: July 18, 2024
    Date Judgment Filed with Courts: March 24, 2025
    Date of Sale: To Be Announced

This helper tries the legacy table parser first (still used by some
counties / older pages); when that yields nothing, falls back to the
paragraph/regex parser that scans the rendered text and pulls each
"Tax ID# … Property Address …" block. The fallback is very tolerant:
it accepts whitespace/HTML between fields, missing fields, and
arbitrary order, so it works across all five accordion-style counties.
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

# ---------- paragraph-fallback patterns --------------------------------------
# Permissive parcel-field preamble. Accepts:
#   Tax ID#: / Tax ID:                     (Wake)
#   Parcel #: / Parcel: / Parcel ID:
#   Parcel Number: / Parcel Numbers:       (New Hanover)
#   PIN: / PIN #:                          (Forsyth)
#   REID:                                  (some counties)
# Captures the trailing alphanumeric value (digits/dashes/dots, must
# contain a digit, length ≥ 6 to skip prose like "PIN number on the").
_PARCEL_PREAMBLE = (
    r"(?:Tax\s*ID(?:\s*#)?|"
    r"Parcel(?:\s*(?:#|Number|ID))?s?|"
    r"PIN(?:\s*#)?|REID)"
)
_PARCEL_FIELD_RE = re.compile(
    _PARCEL_PREAMBLE + r"\s*[:#]\s*(?:<[^>]+>)?\s*([A-Z0-9.\-]{6,})",
    re.I,
)
# Address: Wake uses "Property Address:", Forsyth uses "Description:" (which
# IS the address line in the Forsyth layout), some use "Address:".
_ADDRESS_FIELD_RE = re.compile(
    r"(?:Property\s+Address|Address|Description)\s*:?\s*(?:<[^>]+>)?\s*"
    r"([^<\n\r]+?)"
    r"(?=<br|\n|$|Date\s+of|Tax\s*ID|Amount\s+due|Sale\s+Date|Min\s+Bid)",
    re.I,
)
_AMOUNT_DUE_RE = re.compile(
    r"(?:Amount\s+due|Min\s+Bid|Opening\s+Bid)\s*:?\s*\$?\s*([\d,]+(?:\.\d{2})?)",
    re.I,
)
_DATE_OF_SALE_RE = re.compile(
    r"Sale\s+Date(?:\s*(?:&|and)\s*Time)?\s*:?\s*(?:<[^>]+>)?\s*"
    r"([^<\n\r]+?)(?=<|\n|$|\s+Tax\s*ID|\s+Property|\s+Sale\s+Location"
    r"|\s+Attorney|\s+Approximate)",
    re.I,
)
_DATE_OF_SALE_ALT_RE = re.compile(
    r"Date\s+of\s+Sale\s*:?\s*(?:<[^>]+>)?\s*([^<\n\r]+)", re.I,
)
# Block boundary: the next parcel-preamble. We split on look-ahead so each
# block keeps its preamble for downstream regex matching.
_LISTING_SPLIT_RE = re.compile(
    r"(?=" + _PARCEL_PREAMBLE + r"\s*[:#])", re.I,
)
# Comma-separated multi-parcel: "R08818-001-002-000, R08818-001-004-000, &
# R08818-001-005-000" — each one is a separate physical parcel.
_MULTI_PARCEL_RE = re.compile(r"\b([A-Z0-9.\-]{6,})\b", re.I)


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


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s).replace("&nbsp;", " ")


def _parse_paragraph_blocks(
    *,
    slug: str,
    county: str,
    url: str,
    html: str,
    fallback_sale_date: datetime | None,
    fallback_sale_location: str | None,
) -> list[Listing]:
    """Tolerant paragraph parser for accordion-style county tax pages.

    Splits the page text on each "Tax ID#:" / "Parcel #:" preamble and
    extracts parcel, address, amount-due, and per-listing sale date when
    present. Falls back to page-level sale_date/location when the
    listing block doesn't have its own.
    """
    out: list[Listing] = []
    seen: set[str] = set()
    # Operate on the rendered text to avoid having to re-parse the HTML.
    # We keep <br> as block boundaries by collapsing them to newlines.
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = _strip_html(text)
    # Collapse multi-space but keep line structure.
    text = re.sub(r"[ \t]+", " ", text)

    blocks = _LISTING_SPLIT_RE.split(text)
    for block in blocks:
        # First gather all parcel-like values in this block. Some counties
        # (New Hanover) attach multiple physical parcels to one civil case;
        # we emit one listing per parcel.
        first = _PARCEL_FIELD_RE.search(block)
        if not first:
            continue

        # New-Hanover-style multi-parcel: "Parcel Numbers: A, B, & C" all on
        # ONE line. We collect siblings only up to the first newline (or
        # until we hit the next field name). Going beyond the line picks
        # up unrelated alphanumerics ($16,988.90, the next listing's parcel,
        # block/lot numbers, etc.) and inflates the count.
        preamble_end = first.end()
        sibling_window = block[preamble_end:preamble_end + 300]
        # Hard stop at the FIRST newline OR the next field label. When HTML
        # is stripped the </li><li> boundary becomes a space, so several
        # logical fields end up on one line — we need an explicit bail-out
        # on "Civil Number:", "Sale Date:", "Address:", etc.
        sibling_window = sibling_window.split("\n", 1)[0]
        sibling_window = re.split(
            r"\b(?:Civil\s+Number|Sale\s+Date|Date\s+of\s+Sale|"
            r"Property\s+Address|Address|Description|Amount\s+due|"
            r"Min\s+Bid|Owner|Approximate|Block|Tax\s+Value|Attorney)\b",
            sibling_window, maxsplit=1, flags=re.I,
        )[0]
        parcels: list[str] = [first.group(1).strip()]
        for cand in _MULTI_PARCEL_RE.findall(sibling_window):
            cand = cand.strip()
            if cand == parcels[0]:
                continue
            if not re.search(r"\d", cand) or len(cand) < 6:
                continue
            if re.fullmatch(r"[A-Za-z]+", cand):
                continue
            # Skip dollar amounts (e.g. "16,988.90") — they have commas/dots
            # but no letters. A real parcel typically contains letters or
            # is at least 8+ digits with dashes.
            if re.fullmatch(r"[\d,.]+", cand):
                continue
            parcels.append(cand)

        addr_m = _ADDRESS_FIELD_RE.search(block)
        address = addr_m.group(1).strip() if addr_m else None
        if address:
            address = re.sub(r"\s+", " ", address).rstrip(",.")

        amount_m = _AMOUNT_DUE_RE.search(block)
        amount_due = None
        if amount_m:
            try:
                amount_due = float(amount_m.group(1).replace(",", ""))
            except ValueError:
                amount_due = None

        sale_date_m = _DATE_OF_SALE_RE.search(block) or _DATE_OF_SALE_ALT_RE.search(block)
        sale_date = fallback_sale_date
        if sale_date_m:
            ds = sale_date_m.group(1).strip()
            # "To Be Announced" / "TBA" / "Pending" / "TBD" → keep fallback.
            if not re.search(
                r"^(to\s+be\s+announced|tba|tbd|pending|n/?a|--)$",
                ds, re.I,
            ):
                try:
                    sale_date = dateparser.parse(ds, fuzzy=True)
                except (ValueError, TypeError):
                    pass

        # Civil case number — useful for downstream court-records enrichment.
        civil_m = re.search(r"Civil\s+Number\s*:?\s*([0-9A-Z\-]+)", block, re.I)
        case_no = civil_m.group(1).strip() if civil_m else None

        for parcel in parcels:
            if parcel in seen:
                continue
            seen.add(parcel)
            out.append(Listing(
                source=slug,
                source_url=url,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county=county,
                parcel_id=parcel,
                street_address=address,
                sale_date=sale_date,
                sale_location=fallback_sale_location,
                opening_bid=amount_due,
                case_number=case_no,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={county.lower() + "_tax": {
                    "amount_due": amount_due,
                    "raw_block": block[:600],
                }},
            ))
    return out


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

    Tries the legacy table parser first; when no rows match (most modern
    NC accordion-style pages), falls back to the paragraph parser.

    column_layout values:
      "owner_parcel_desc_file_bid"  — Henderson / older format
      "parcel_owner_desc_file_bid"  — some counties swap col 1+2
    """
    # Retry the fetch up to 3 times with exponential backoff. County
    # tax-administration sites are notoriously flaky during business
    # hours — a single timeout can lose the whole week. The total
    # worst-case is ~25 + 30 + 40 = ~95s, well under the scraper
    # timeout_s default of 60-180s. Carryover handles the case where
    # all retries fail and the source had prior data; this retry layer
    # is what prevents new sources (which carryover can't help) from
    # silently going to zero on a transient blip.
    import asyncio as _asyncio
    html: str | None = None
    last_err: str | None = None
    for attempt in range(3):
        try:
            async with client(timeout=20.0) as c:
                r = await c.get(url, headers=HEADERS)
            if r.status_code == 200 and r.text and len(r.text) >= 500:
                html = r.text
                break
            last_err = f"status={r.status_code} bytes={len(r.text or '')}"
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {str(exc)[:120]}"
        if attempt < 2:
            await _asyncio.sleep(2 ** attempt + 1)  # 2s, 3s

    if html is None:
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

    if out:
        return out

    # Table parser found nothing — try the paragraph parser used by Wake,
    # Forsyth, Guilford, Durham, New Hanover, etc.
    return _parse_paragraph_blocks(
        slug=slug, county=county, url=url, html=html,
        fallback_sale_date=sale_date, fallback_sale_location=sale_location,
    )
