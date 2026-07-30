"""Cleveland NC tax foreclosure sales — county Legal Department (in-house).

Cleveland County runs its tax foreclosure sales IN-HOUSE through its own Legal
Department (contact christie.wooten@clevelandcountync.gov / 704-476-3089), NOT
through an outside firm. (A minority of parcels are farmed out to Kania Law
Firm; the page links those separately and we scrape Kania on its own.)

The authoritative in-house page is:
  https://www.clevelandcounty.com/main/departments/
  find_tax_foreclosures___county_owned_properties_for_sale/index.php

It publishes the same properties in TWO shapes and we parse BOTH:

1. A "Ninja Tables" grid of SCHEDULED auction sales — the highest-value rows,
   each carrying a real sale date + opening bid. Cells are tagged with semantic
   `ninja_clmn_nm_*` classes (county / address / parcel / saledatetime /
   openingbid / currentbid / closedate / propertytype / courtfile / ourfile).
   One row may pack two parcels (address + parcel cells split on <br>).

2. Numbered inline <p>/<li> text for (a) the item in its 10-day upset-bid window
   and (b) "PROPERTIES CURRENTLY IN FORECLOSURE" pending items, shaped:
     "Parcel[:] <id> / File # <case#> / [Address:] <address> / Map ..."

Cleveland's mod_security blocks a bare "Mozilla/5.0" UA, so we send a full
Chrome UA + Accept headers.
"""
from __future__ import annotations

import html as _html
import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser, Node

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

URL = ("https://www.clevelandcounty.com/main/departments/"
       "find_tax_foreclosures___county_owned_properties_for_sale/index.php")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_BR = re.compile(r"<br\s*/?>", re.I)
# Tolerant inline entry pattern:
#   "Parcel[:] <id> / File # <case#> / [Address:] <address> / Map ..."
# "Parcel" may carry an optional colon and the "/" separators may be padded
# with &nbsp; (decoded before matching). The address runs up to the next "/".
ENTRY_RE = re.compile(
    r"Parcel:?\s*(?P<parcel>\d+)\s*/\s*File\s*#\s*(?P<file>[\dA-Za-z\-]+)\s*/\s*"
    r"(?:Address:\s*)?(?P<addr>[^/]+)",
    re.I,
)
# Sale date, when present in a section header preceding a scheduled listing.
DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},?\s+\d{4}"
    r"(?:\s+at\s+\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)?",
    re.I,
)

_PROPERTY_KIND = {
    "residential home": PropertyKind.SINGLE_FAMILY,
    "residential vacant lot": PropertyKind.LAND,
    "vacant lot": PropertyKind.LAND,
    "land": PropertyKind.LAND,
    "commercial": PropertyKind.COMMERCIAL,
    "mixed": PropertyKind.MIXED,
}


def _cell(row: Node, name: str) -> Node | None:
    """The <td> in `row` whose class carries `ninja_clmn_nm_<name>`."""
    return row.css_first(f"td.ninja_clmn_nm_{name}")


def _lines(node: Node | None) -> list[str]:
    """Split a cell's inner HTML on <br> into clean, non-empty text lines."""
    if node is None:
        return []
    out = []
    for seg in _BR.split(node.html or ""):
        txt = _WS.sub(" ", _html.unescape(_TAG.sub(" ", seg))).strip()
        if txt and txt not in {"\xa0", ""}:
            out.append(txt)
    return out


def _text(node: Node | None) -> str:
    return _lines(node) and " ".join(_lines(node)) or ""


def _money(s: str) -> float | None:
    m = re.search(r"([\d,]+(?:\.\d{2})?)", s or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _date(s: str):
    if not s or not s.strip():
        return None
    try:
        return dateparser.parse(s)
    except (ValueError, TypeError, OverflowError):
        return None


def _now() -> datetime:
    return datetime.utcnow()


def _parse_sales_table(html: str) -> list[Listing]:
    """Parse the Ninja-Tables grid of SCHEDULED in-house auction sales.

    These rows are the primary product of this page (real sale date + opening
    bid) and are NOT in the inline "Parcel / File #" shape, so the inline regex
    alone silently dropped them. A single row can pack two parcels (address and
    parcel cells split on <br>): we emit one Listing per parcel.
    """
    out: list[Listing] = []
    tree = HTMLParser(html)
    for row in tree.css("table tr"):
        # Only rows that actually carry the semantic sale columns.
        if _cell(row, "parcel") is None and _cell(row, "saledatetime") is None:
            continue
        parcels = _lines(_cell(row, "parcel"))
        addresses = _lines(_cell(row, "address"))
        if not parcels and not addresses:
            continue
        county = _text(_cell(row, "county")) or "Cleveland"
        county = county.replace(" County", "").strip() or "Cleveland"
        sale_date = _date(_text(_cell(row, "saledatetime")))
        opening_bid = _money(_text(_cell(row, "openingbid")))
        current_bid = _money(_text(_cell(row, "currentbid")))
        close_date = _text(_cell(row, "closedate"))
        ptype_raw = _text(_cell(row, "propertytype"))
        kind = _PROPERTY_KIND.get(ptype_raw.strip().lower(), PropertyKind.UNKNOWN)
        case_no = _text(_cell(row, "courtfile")) or None
        our_file = _text(_cell(row, "ourfile")) or None

        # Pair parcels with addresses. When counts match (>1), emit one Listing
        # per parcel; otherwise emit a single row (first parcel, joined address).
        if len(parcels) == len(addresses) and len(parcels) > 1:
            pairs = list(zip(parcels, addresses))
        else:
            pairs = [(
                parcels[0] if parcels else None,
                " / ".join(addresses) if addresses else None,
            )]

        for parcel, addr in pairs:
            out.append(
                Listing(
                    source="counties_nc.cleveland_tax",
                    source_url=URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=kind,
                    state="NC",
                    county=county,
                    parcel_id=parcel,
                    street_address=addr,
                    sale_date=sale_date,
                    case_number=case_no,
                    opening_bid=opening_bid,
                    description=(
                        f"Cleveland County in-house tax foreclosure sale — "
                        f"{ptype_raw or 'property'}; opening bid "
                        f"{('$%.2f' % opening_bid) if opening_bid else '?'}"
                    ),
                    first_seen=_now(),
                    last_seen=_now(),
                    raw={"cleveland_tax": {
                        "stage": "scheduled",
                        "our_file": our_file,
                        "close_date": close_date or None,
                        "current_bid": current_bid,
                        "property_type": ptype_raw or None,
                    }},
                )
            )
    return out


def _parse_inline(html: str) -> list[Listing]:
    """Parse the inline upset-bid item + 'CURRENTLY IN FORECLOSURE' pending items."""
    # Decode HTML entities BEFORE flattening whitespace: the page pads its "/"
    # separators with literal &nbsp; entities (e.g. "Parcel 57139 /&nbsp; File #").
    # Without unescape these survive as literal text and break the "/ File"
    # boundary, silently dropping the scheduled/upset-bid inline listing.
    flat = _WS.sub(" ", _html.unescape(_TAG.sub(" ", html)))
    out: list[Listing] = []
    seen: set[tuple[str, str]] = set()

    # Properties after the "CURRENTLY IN FORECLOSURE" marker are pending (no sale
    # yet); those before it are in the 10-day upset-bid window.
    marker = flat.upper().find("CURRENTLY IN FORECLOSURE")

    for m in ENTRY_RE.finditer(flat):
        parcel = m.group("parcel")
        file_no = m.group("file")
        key = (parcel, file_no)
        if key in seen:
            continue
        seen.add(key)
        addr = (m.group("addr") or "").strip().rstrip("/").strip()
        pending = marker > 0 and m.start() > marker

        sale_date = None
        if not pending:
            dm = DATE_RE.search(flat[max(0, m.start() - 180):m.start()])
            if dm:
                sale_date = _date(dm.group(0))

        out.append(
            Listing(
                source="counties_nc.cleveland_tax",
                source_url=URL,
                listing_type=ListingType.LIS_PENDENS if pending else ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county="Cleveland",
                parcel_id=parcel,
                street_address=addr or None,
                sale_date=sale_date,
                case_number=file_no,
                description=m.group(0)[:500],
                auction_status="pending" if pending else None,
                first_seen=_now(),
                last_seen=_now(),
                raw={"cleveland_tax": {"entry": m.group(0)[:500],
                                       "stage": "pending" if pending else "upset_bid"}},
            )
        )
    return out


def parse(html: str) -> list[Listing]:
    """Parse both the scheduled-sales table and the inline items from the page.

    Dedup across both shapes on (parcel_id, case_number) so a property that
    appears in the grid is not re-emitted from any inline text.
    """
    rows = _parse_sales_table(html) + _parse_inline(html)
    out: list[Listing] = []
    seen: set[tuple[str | None, str | None]] = set()
    for r in rows:
        key = (r.parcel_id, r.case_number)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


class ClevelandTaxForeclosure(BaseScraper):
    slug = "counties_nc.cleveland_tax"
    name = "Cleveland NC Tax Foreclosure Sales"
    category = "county_tax"
    expected_min_count = 3
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=20.0) as c:
            r = await c.get(URL, headers=HEADERS)
            if r.status_code != 200:
                return []
            html = r.text
        return parse(html)
