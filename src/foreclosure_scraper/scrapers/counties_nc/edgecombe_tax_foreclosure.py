"""Edgecombe County NC - Tax Foreclosure properties.

Edgecombe County publishes tax foreclosure properties on its county
website as a single flat table, columns in this FIXED order (confirmed
live 2026-09-15):

    PROPERTY DESCRIP. | TWN SHP | PARCEL | STATUS | FILE NO.

e.g. "204 Neville St., Princeville | 1 | 4738-71-6101-00 |
Complaint filed/Settlement pending | 25CV003307-320". There is no owner
column at all.

FOUND 2026-09-15 (background triage agent, this codebase's zero-row-
scraper audit; confirmed live by hand before rewriting): the ORIGINAL
version of this module carried `active_months=(1..8)` and reported
DORMANT every September-December -- live-checked 2026-09-15 (September)
and the table has multiple current rows, several with 2026 case numbers
(26CV000562-3208, 26CV001028-320, 26CV001041-320). Gate simply wrong;
removed, same reasoning as wake_tax_foreclosure.py.

It ALSO mapped columns wrong even when it did run: `clean[0]` (the
PROPERTY DESCRIPTION, i.e. the address) was labeled `owner`, and the
address-extraction loop only searched `clean[1:]` for a digit+word
pattern -- skipping right past the real address sitting in `clean[0]`.
Rewritten to use the known fixed column order directly instead of
heuristic guessing.

Free, public, no login.
Slug: counties_nc.edgecombe_tax_foreclosure
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://www.edgecombecountync.gov/businesses/tax_collector/tax_foreclosure_list.php"

_PARCEL_RE = re.compile(r"\b\d{4}-\d{2}-\d{4}(?:-\d{2})?\b")
_CASE_RE = re.compile(r"\b\d{2}CV\d{6}-\d{2,4}\b", re.I)
# STATUS sometimes carries the actual scheduled auction date directly
# ("Sale 9/16/2026") rather than just a case-progress note -- a real,
# higher-priority signal than the "Complaint filed" rows, worth its own
# sale_date rather than leaving it buried in free text.
_SALE_STATUS_RE = re.compile(r"\bSale\s+(\d{1,2})/(\d{1,2})/(\d{4})\b", re.I)


class EdgecombeTaxForeclosure(BaseScraper):
    slug = "counties_nc.edgecombe_tax_foreclosure"
    name = "Edgecombe County NC Tax Foreclosures"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("edgecombe_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        now = datetime.utcnow()
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 5:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip() for c in cells]
            address, township, parcel_raw, status, file_no = clean[0], clean[1], clean[2], clean[3], clean[4]

            if not _PARCEL_RE.search(parcel_raw):
                continue   # header row, section divider ("Ct 1"), or blank spacer row
            if any(h in address.lower() for h in ("property descrip", "tax foreclosure list")):
                continue

            parcel = _PARCEL_RE.search(parcel_raw).group(0)
            case_no = _CASE_RE.search(file_no)
            case_number = case_no.group(0) if case_no else (file_no or None)
            sale_m = _SALE_STATUS_RE.search(status)
            sale_date = (datetime(int(sale_m.group(3)), int(sale_m.group(1)), int(sale_m.group(2)))
                         if sale_m else None)

            out.append(Listing(
                source=self.slug,
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county="Edgecombe",
                parcel_id=parcel,
                street_address=address or None,
                case_number=case_number,
                sale_date=sale_date,
                auction_status=status or None,
                description=(f"Edgecombe County tax foreclosure: {status}" if status
                             else "Edgecombe County tax foreclosure"),
                first_seen=now,
                last_seen=now,
                raw={"edgecombe_tax_foreclosure": {
                    "township": township,
                    "status": status,
                    "file_no": file_no,
                    "cells": clean[:7],
                }},
            ))

        log.info("edgecombe_tax.done", count=len(out))
        return out
