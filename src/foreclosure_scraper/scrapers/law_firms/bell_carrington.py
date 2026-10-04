"""Bell Carrington Price & Gregg — pulls directly from their published Google Sheets CSV.

The bellcarrington.com/foreclosure-sales/ page embeds a Google Sheets iframe.
We bypass the iframe and hit the public CSV export endpoint directly. Returns
~90 rows across AL/GA/LA/NC/SC/TN; filtered to SC + NC.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

# The "Notes" column sometimes carries the real court case number for NC rows
# (e.g. "26SP000141-280") rather than a free-text note — live-verified
# 2026-10-01. When it matches, promote it to case_number instead of only
# description, same as every other law_firms.* scraper.
CASE_NO_RE = re.compile(r"^\d{2}SP\d{5,7}-\d{2,4}$")

# When "Bid" is a status word instead of a dollar amount, the sale was not
# held as originally scheduled. Live-verified 2026-10-04: a "Postponed" row
# carries its NEW sale date/time in Notes (e.g. "11/12/2026 at 11:30 AM")
# instead of a case number or free text -- the original Sale Date column
# still shows the OLD, superseded date. Without this, a postponed sale ships
# with a stale sale_date and no indication the listed date already passed.
_STATUS_RE = re.compile(r"postpon|cancel|withdraw", re.I)
_STATUS_MAP = {"postpon": "postponed", "cancel": "cancelled", "withdraw": "withdrawn"}

CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vSIUFqSQg76o_XFa1uQePxCuubohTs9JG4ptdzpR7dqTZj1JwkjracxTF9IPqqPExAADyxzuWS8teaD"
    "/pub?gid=0&single=true&output=csv"
)


class BellCarrington(BaseScraper):
    slug = "law_firms.bell_carrington"
    name = "Bell Carrington Price & Gregg"
    category = "law_firm"
    timeout_s = 60.0
    expected_min_count = 30  # multi-state CSV typically has 60-90 rows

    async def fetch(self) -> Iterable[Listing]:
        try:
            csv_text = await get_text(CSV_URL, timeout=30.0)
        except Exception:
            return []

        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        if len(rows) < 2:
            return []

        # Header row keys: Sale Date | State | Property | City | Zip | County | Bid | Notes
        # State-only header rows have only the State column populated; skip them.
        out: list[Listing] = []
        for row in rows[1:]:
            if len(row) < 6:
                continue
            sale_raw = (row[0] or "").strip()
            state = (row[1] or "").strip().upper()
            prop = (row[2] or "").strip()
            city = (row[3] or "").strip()
            zip_code = (row[4] or "").strip()
            county = (row[5] or "").strip().replace(" County", "")
            bid_raw = (row[6] or "").strip() if len(row) > 6 else ""
            notes = (row[7] or "").strip() if len(row) > 7 else ""

            if state not in ("SC", "NC"):
                continue
            if not prop or not sale_raw:
                continue

            sale_date = None
            try:
                sale_date = dateparser.parse(sale_raw)
            except (ValueError, TypeError):
                continue  # require valid date

            bid = None
            auction_status = None
            bm = re.search(r"\$?\s*([\d,]+(?:\.\d{2})?)", bid_raw)
            if bm:
                try:
                    bid = float(bm.group(1).replace(",", ""))
                except ValueError:
                    pass
            else:
                sm = _STATUS_RE.search(bid_raw)
                if sm:
                    auction_status = _STATUS_MAP[sm.group(0).lower()]

            case_number = notes if (notes and CASE_NO_RE.match(notes)) else None

            # A postponed sale's Notes column is the new sale date/time, not
            # a case number or free text -- prefer it as the effective
            # sale_date over the now-superseded original Sale Date value.
            if auction_status == "postponed" and notes and not case_number:
                try:
                    new_date = dateparser.parse(notes, fuzzy=True)
                except (ValueError, TypeError):
                    new_date = None
                if new_date:
                    sale_date = new_date

            out.append(
                Listing(
                    source=self.slug,
                    source_url="https://bellcarrington.com/foreclosure-sales/",
                    listing_type=ListingType.FORECLOSURE_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=prop,
                    city=city or None,
                    state=state,
                    zip_code=zip_code or None,
                    county=county or None,
                    sale_date=sale_date,
                    opening_bid=bid,
                    auction_status=auction_status,
                    case_number=case_number,
                    trustee="Bell Carrington Price & Gregg",
                    description=None if case_number else (notes[:300] or None),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
            )
        return out
