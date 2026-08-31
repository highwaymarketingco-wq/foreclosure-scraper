"""McDowell County NC — Tax Foreclosure sales.

McDowell County publishes upcoming tax-foreclosure sales at
mcdowellnc.gov/departments/tax-collections/tax-foreclosures/upcoming-tax-foreclosure-sales.

The page carries up to three tables, all free/public/no-login:

  1. SCHEDULED SALES — SALE DATE | SALE TIME | PARCEL NUMBER | OPENING BID
     AMOUNT | FILE NUMBER.  (Often the placeholder row
     "NO FORECLOSURE SALES SCHEDULED AT THIS TIME" when nothing is on the
     calendar — a legit empty, not an error.)
  2. UPSET-BID PERIOD (pending) — ORIGINAL SALE DATE | 10-DAY UPSET BID
     PERIOD ENDS | PARCEL NUMBER | HIGHEST BID RECORDED | FILE NUMBER.
  3. PENDING (no sale date yet) — PARCEL NUMBER | FILE NUMBER.

There is no owner name or street address on the page — the county lists the
parcel PIN + the court file number only, so parcel_id is the property key.

Gate with FORECLOSURE_MCDOWELL_FCL=0 to skip.
Slug: counties_nc.mcdowell_tax_foreclosure
Category: foreclosure
ListingType: FORECLOSURE_SALE  (tax foreclosure — foreclosure_process="tax")
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = (
    "https://mcdowellnc.gov/departments/tax-collections/"
    "tax-foreclosures/upcoming-tax-foreclosure-sales"
)

ENV_OFF = "FORECLOSURE_MCDOWELL_FCL"

# Rows that are the county's "nothing scheduled" placeholder, not real data.
_PLACEHOLDER_RE = re.compile(r"no\s+foreclosure\s+sales?\s+scheduled", re.I)


def _clean(v: object) -> str:
    """Cell text -> trimmed string ('' for NaN / None)."""
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("nan", "none"):
        return ""
    return s


def _to_float(s: str) -> float | None:
    """'$ 9,687.38' -> 9687.38."""
    if not s:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _to_date(s: str) -> datetime | None:
    """Parse MM/DD/YYYY (also M/D/YY, MM-DD-YYYY) -> datetime, else None."""
    if not s:
        return None
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", s)
    if not m:
        return None
    mo, day, yr = m.groups()
    yr_i = int(yr)
    if yr_i < 100:
        yr_i += 2000
    try:
        return datetime(yr_i, int(mo), int(day))
    except ValueError:
        return None


def _first_parcel(s: str) -> str | None:
    """A cell may hold two PINs ('1739-00-31-2535 / 1739-00-21-7533').
    Return the first as the canonical parcel_id; keep the full string in raw."""
    if not s:
        return None
    # McDowell PINs look like 1739-00-31-2535; also accept plain digit runs.
    m = re.search(r"\d{4}-\d{2}-\d{2}-\d{3,4}", s)
    if m:
        return m.group(0)
    m = re.search(r"\b\d{6,}\b", s)
    if m:
        return m.group(0)
    return None


def _col_index(header: list[str], *needles: str) -> int | None:
    """Index of the first header cell containing any needle (case-insensitive)."""
    for i, h in enumerate(header):
        hl = h.lower()
        if any(n in hl for n in needles):
            return i
    return None


class McDowellTaxForeclosure(BaseScraper):
    slug = "counties_nc.mcdowell_tax_foreclosure"
    name = "McDowell County NC Tax Foreclosures"
    category = "foreclosure"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("mcdowell_tax_fcl.skipped_env")
            return out

        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=45.0)
        except Exception as exc:  # noqa: BLE001 - never raise out of a scraper
            log.warning("mcdowell_tax_fcl.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        try:
            import pandas as pd

            dfs = pd.read_html(io.StringIO(html))
        except Exception as exc:  # noqa: BLE001 - no tables / parse error
            log.warning("mcdowell_tax_fcl.read_html_fail", error=str(exc)[:160])
            return out

        now = datetime.utcnow()
        seen_keys: set[tuple] = set()

        for df in dfs:
            if df.shape[0] < 2:
                continue
            rows = df.values.tolist()
            header = [_clean(c) for c in rows[0]]

            # Only treat this as a foreclosure table if the header names a parcel.
            i_parcel = _col_index(header, "parcel", "pin")
            if i_parcel is None:
                continue
            i_file = _col_index(header, "file")
            i_sale = _col_index(header, "sale date", "original sale")
            i_time = _col_index(header, "sale time")
            # NB: match only the money columns; a bare "bid" needle would hit
            # "10-DAY UPSET BID PERIOD ENDS" (a date column) first.
            i_bid = _col_index(header, "opening bid", "highest bid")
            i_upset = _col_index(header, "upset")

            for raw_row in rows[1:]:
                cells = [_clean(c) for c in raw_row]
                if not cells:
                    continue
                joined = " ".join(cells)
                if _PLACEHOLDER_RE.search(joined):
                    continue  # "NO FORECLOSURE SALES SCHEDULED AT THIS TIME"

                parcel_cell = cells[i_parcel] if i_parcel < len(cells) else ""
                parcel = _first_parcel(parcel_cell)
                file_no = (
                    cells[i_file] if (i_file is not None and i_file < len(cells)) else None
                ) or None
                if not parcel and not file_no:
                    continue

                sale_date = (
                    _to_date(cells[i_sale])
                    if (i_sale is not None and i_sale < len(cells))
                    else None
                )
                upset_deadline = (
                    _to_date(cells[i_upset])
                    if (i_upset is not None and i_upset < len(cells))
                    else None
                )
                bid = (
                    _to_float(cells[i_bid])
                    if (i_bid is not None and i_bid < len(cells))
                    else None
                )
                sale_time = (
                    cells[i_time]
                    if (i_time is not None and i_time < len(cells))
                    else None
                ) or None

                key = (parcel or "", file_no or "")
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                if upset_deadline is not None:
                    stage = "upset_bid_period"
                elif sale_date is not None:
                    stage = "scheduled_sale"
                else:
                    stage = "pending"

                desc_bits = [f"McDowell County NC tax foreclosure ({stage})"]
                if file_no:
                    desc_bits.append(f"File {file_no}")
                if sale_date:
                    desc_bits.append(f"Sale {sale_date:%m/%d/%Y}")
                if upset_deadline:
                    desc_bits.append(f"Upset ends {upset_deadline:%m/%d/%Y}")
                if bid is not None:
                    desc_bits.append(f"Bid ${bid:,.2f}")

                out.append(Listing(
                    source=self.slug,
                    source_url=PAGE_URL,
                    listing_type=ListingType.FORECLOSURE_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="McDowell",
                    parcel_id=parcel,
                    case_number=file_no,
                    sale_date=sale_date,
                    upset_bid_deadline=upset_deadline,
                    opening_bid=bid,
                    foreclosure_process="tax",
                    description=" | ".join(desc_bits),
                    first_seen=now,
                    last_seen=now,
                    raw={"mcdowell_tax_foreclosure": {
                        "stage": stage,
                        "parcel_raw": parcel_cell or None,
                        "file_number": file_no,
                        "sale_time": sale_time,
                        "cells": cells[:8],
                    }},
                ))

        log.info("mcdowell_tax_fcl.done", count=len(out))
        return out
