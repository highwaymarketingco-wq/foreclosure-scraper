"""Oconee County SC delinquent-tax sale list — published Google Sheet CSV.

Oconee publishes its annual delinquent-tax sale list as a "Published to the
web" Google Sheet embedded on oconeesc.com/delinquent-tax/sale-list; the same
doc serves CSV via the standard pub?output=csv endpoint (free, no key, no
bypass). Between sale cycles the sheet holds only announcement placeholder
rows (no Item / Map number) — those are skipped. Real rows appear in late
October ahead of the November sale.

Columns: Item Number | Owner Name | Map Number (TMS) | Description | Total Tax Due
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Iterable

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

# 'Published to the web' doc id for the Oconee delinquent-tax sale list.
_PUB_ID = ("2PACX-1vS_1zk5YJkcpDyEWM819KI6BNDYhcHzDKLfYc-"
           "LassQL9F02mrPirb2-6doQwL6PVHqz85f6I2eBF-1")
CSV_URL = f"https://docs.google.com/spreadsheets/d/e/{_PUB_ID}/pub?output=csv"
PAGE_URL = "https://oconeesc.com/delinquent-tax/sale-list"

_MONEY = re.compile(r"[\d,]+(?:\.\d{2})?")

# The sheet's own announcement placeholder rows (no Item/Map number) state the
# county-wide auction date in free text, e.g. "The 2026 Tax Sale is scheduled
# for Monday, November 9, 2026." Every real item on the list shares that one
# sale date (it is not published per-row), so we parse it once from whichever
# placeholder row carries it and stamp it onto every real row. Without this,
# sale_date is never set at all and the horizon filter in main.py's
# _active_only() needs a DATELESS_OK_SOURCES entry just to keep the rows (kept
# as a backstop below in case this text format ever changes and parsing fails).
_SALE_DATE_RE = re.compile(
    r"scheduled for\s+\w+,?\s+([A-Za-z]+ \d{1,2},?\s*\d{4})", re.I
)


def _parse_sale_date(text: str) -> datetime | None:
    m = _SALE_DATE_RE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _parse_csv(text: str) -> list[Listing]:
    rows = list(csv.DictReader(io.StringIO(text)))

    # First pass: find the county-wide sale date from the announcement text,
    # wherever it appears among the columns of any row.
    sale_date: datetime | None = None
    for row in rows:
        for val in row.values():
            if not val:
                continue
            sale_date = _parse_sale_date(str(val))
            if sale_date:
                break
        if sale_date:
            break

    out: list[Listing] = []
    for row in rows:
        item = (row.get("Item Number") or "").strip()
        tms = (row.get("Map Number") or "").strip()
        # A real listing has BOTH an item number and a map (TMS) number; the
        # announcement/placeholder rows have neither.
        if not item or not tms:
            continue
        owner = (row.get("Owner Name") or "").strip() or None
        desc = (row.get("Description") or "").strip() or None
        amount = None
        m = _MONEY.search((row.get("Total Tax Due") or "").strip())
        if m:
            try:
                amount = float(m.group(0).replace(",", ""))
            except ValueError:
                pass
        out.append(Listing(
            source="counties_sc.oconee_tax_sale", source_url=PAGE_URL,
            listing_type=ListingType.TAX_SALE, property_kind=PropertyKind.UNKNOWN,
            state="SC", county="Oconee",
            parcel_id=tms, defendant=owner, judgment_amount=amount,
            sale_date=sale_date,
            description="Oconee tax sale item " + item + (f" — {desc}" if desc else ""),
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw={"oconee_tax_sale": {
                "item": item, "tax_due": amount, "owner": owner,
                "sale_date": sale_date.date().isoformat() if sale_date else None,
            }},
        ))
    return out


class OconeeTaxSale(BaseScraper):
    slug = "counties_sc.oconee_tax_sale"
    name = "Oconee SC Delinquent Tax Sale (published CSV)"
    category = "county_tax"
    expected_min_count = 0   # placeholder-only between sale cycles (real rows ~late Oct)
    timeout_s = 40.0

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=30.0) as c:
            r = await c.get(CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                return []
            text = r.text
        return _parse_csv(text)
