"""Rowan County NC delinquent real-estate tax list (the county's own spreadsheet).

SOURCE
    rowancountync.gov/1525/Delinquent-Taxpayer-Lists publishes one spreadsheet per tax year
    ("Download 2025 List (XLS)" -> DocumentCenter/View/55256 on 2026-10-07; the 2016-2024 files
    stay up). The 2025 file: 6,543 rows, 71 columns, every row tax_year 2025, ar_status OPEN,
    parcel_advertised Y; report_group_description REAL 2,699, PP 3,839 (personal property),
    UT 4 (utility). ONLY REAL rows are read: a vehicle or business-equipment bill is not a
    distressed parcel. The newest year's file is found on the page each run.

ROW
    One lead per parcel: parcel_number, owner (taxpayer_name_1/_2), taxpayer mailing address
    (raw owner_mailing, never the property's address), situs (asset_description, e.g.
    "123 MAIN ST"), assessed value, balance_due. type_of_id HRS (heirs) and ETA (estate) are kept
    as raw flags (117 and 56 rows in the whole 2025 file).

THE NOT-YET-LATE RULE (tax_calendar, _tax_kit)
    A 2025 levy is late since 2026-01-06, so these bills count. A row whose levy year is not late
    yet (a future file read before January 6) is dropped, and raw['tax_owed'] counts only late
    years: {balance, kind, source, year, basis 'advertised_list', years_delinquent, ...}.

DATELESS: no sale date; slug counties_nc.rowan_delinquent_tax goes in
main.DATELESS_OK_SOURCES. Gate: FORECLOSURE_ROWAN_TAX=0.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...sensitive_fields import drop_sensitive
from ..counties_generic._layer_kit import clean, num, owner_mailing
from ..counties_generic._tax_kit import tax_owed_block

log = structlog.get_logger()

SLUG = "counties_nc.rowan_delinquent_tax"
ENV_OFF = "FORECLOSURE_ROWAN_TAX"
PAGE = "https://www.rowancountync.gov/1525/Delinquent-Taxpayer-Lists"
BASE = "https://www.rowancountync.gov"

_LINK = re.compile(r'href="(/DocumentCenter/View/\d+)[^"]*"[^>]*>\s*(?:<[^>]+>\s*)*Download\s+(\d{4})\s+List\s+\(XLS\)',
                   re.I)


def newest_xls(page_html: str) -> Optional[tuple[int, str]]:
    """(tax year, absolute URL) of the newest 'Download <year> List (XLS)' link."""
    found = [(int(y), BASE + href) for href, y in _LINK.findall(page_html or "")]
    return max(found) if found else None


def rows_from_sheet(rows: list[list[str]]) -> list[dict]:
    if not rows:
        return []
    hdr = [h.strip() for h in rows[0]]
    return [drop_sensitive(dict(zip(hdr, r + [""] * (len(hdr) - len(r))))) for r in rows[1:]]


def to_listing(rec: dict, url: str, *, now: Optional[datetime] = None) -> Optional[Listing]:
    if (rec.get("report_group_description") or "").strip().upper() != "REAL":
        return None
    parcel = clean(rec.get("parcel_number"))
    situs = clean(rec.get("asset_description"))
    if not (parcel or situs):
        return None
    year = clean(rec.get("tax_year"))
    bal = num(rec.get("balance_due"))
    to = tax_owed_block([(year, bal)], state="NC", county="Rowan", source=SLUG,
                        basis="advertised_list")
    if not to:
        return None                       # the only unpaid bill is not late yet
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    owners = [o for o in (clean(rec.get("taxpayer_name_1")), clean(rec.get("taxpayer_name_2"))) if o]
    owner = " & ".join(owners) or None
    id_type = (clean(rec.get("type_of_id")) or "").upper()
    block: dict[str, Any] = {
        "tax_year": year, "bill_number": clean(rec.get("bill_number")),
        "balance_due": bal, "total_due": num(rec.get("total_due")),
        "interest_due": num(rec.get("Interest Due")), "assessed_value": num(rec.get("assessed_value")),
        "years_unpaid": [int(year)] if year and year.isdigit() else [],
        "owner_type": id_type or None, "ar_status": clean(rec.get("ar_status")),
        "list_url": url,
    }
    raw: dict[str, Any] = {"rowan_delinquent_tax": block, "tax_owed": to}
    if id_type in ("HRS", "ETA"):
        raw["heirs_or_estate_owner"] = {"type": id_type, "source": SLUG}
    mail = owner_mailing(owner, (rec.get("taxpayer_address_line_1"), rec.get("taxpayer_address_line_2"),
                                 rec.get("taxpayer_city"), rec.get("taxpayer_state"), rec.get("taxpayer_zip")),
                         rec.get("taxpayer_state"), situs, parcel, "NC", "rowan_delinquent_tax")
    if mail:
        raw["owner_mailing"] = mail
    return Listing(
        source=SLUG, source_url=url,
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Rowan",
        street_address=situs, parcel_id=parcel,
        owner_name=owner, defendant=owner,
        assessed_value=num(rec.get("assessed_value")),
        legal_description=clean(" ".join(rec.get(k) or "" for k in
                                         ("legal_description_1", "legal_description_2", "legal_description_3"))),
        foreclosure_process="tax",
        description=f"Rowan NC delinquent {year} real-estate tax ${bal or 0:,.0f} — {owner or ''} {situs or parcel}"[:300],
        first_seen=now, last_seen=now,
        raw=raw,
    )


class RowanDelinquentTax(BaseScraper):
    slug = SLUG
    name = "Rowan County NC delinquent real-estate tax list (county XLSX)"
    category = "county_tax"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF) == "0":
            return []
        from .._xlsx_stdlib import read_rows
        async with client(timeout=90.0) as c:
            r = await c.get(PAGE)
            if r.status_code != 200:
                raise RuntimeError(f"rowan page HTTP {r.status_code}")
            found = newest_xls(r.text)
            if not found:
                raise RuntimeError("rowan: no 'Download <year> List (XLS)' link on the page")
            year, url = found
            x = await c.get(url, timeout=120.0)
            if x.status_code != 200:
                raise RuntimeError(f"rowan xlsx HTTP {x.status_code}")
        recs = rows_from_sheet(read_rows(x.content))
        out = [li for li in (to_listing(rec, url) for rec in recs) if li]
        log.info("rowan_tax.done", year=year, rows=len(recs), leads=len(out))
        return out
