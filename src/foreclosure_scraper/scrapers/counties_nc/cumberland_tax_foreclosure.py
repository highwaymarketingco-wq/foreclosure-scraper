"""Cumberland County NC - Tax Foreclosure properties.

Cumberland County publishes tax foreclosure properties in a dynamic
(Sitefinity CMS) table, columns in this FIXED order (confirmed live
2026-10-01):

    Owners Name | Property Location | Parcel Number | Bill Number | Sale Date

e.g. "Weeks, John | 14.89 ACS Wade Elementary School | 0582604198000 |
398277 | Jul 7, 2026". "Property Location" is usually a legal/plat
description ("BLAWELL LO:10 PL:0035-0010"), not a mailing address, but a
minority of rows DO carry a real street address ("RES 872 Southern Ave");
promote those to ``street_address`` and keep the rest as
``legal_description`` only.

FIXED 2026-10-01 (batch-5 extraction-completeness audit): the module's
PAGE_URL (``/departments/tax/tax-administration/tax-foreclosures``) is
STALE -- the county's site reorg moved this page to
``/departments/tax-group/tax/tax-foreclosure-sales``. The stale URL still
answers HTTP 200, but silently serves the generic "Tax Administration"
landing page instead (classic silent-200 failure, no 404). That landing
page's only `<table>` elements are the office's own "Phone / Fax /
Address" contact-info footer (class ``contact-us-table``) -- the OLD
blind "parse every `<tr>` on the page" scraper was parsing THAT as if it
were real listings, emitting rows like owner="Phone:" address="117 Dick
Street, Room 530 ...". Also: `sale_date` was never parsed at all, so
every row (garbage or real) was being silently dropped downstream by
`_active_only()` regardless (this slug was never in DATELESS_OK_SOURCES).
Rewritten to: (1) use the live URL, (2) find the real data table by its
header cells rather than trusting it is the first/only `<table>` on the
page, (3) parse `sale_date`, (4) drop the stray " (?)" tooltip-icon
suffix Sitefinity appends to the owner cell.

Free, public, no login.
Slug: counties_nc.cumberland_tax_foreclosure
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

PAGE_URL = "https://www.co.cumberland.nc.us/departments/tax-group/tax/tax-foreclosure-sales"

# Legal/plat-description markers that mean "Property Location" is NOT a usable
# mailing address (acreage tract, lot/plat/block reference) even when it
# happens to start with a number ("14.89 ACS ...").
_LEGAL_DESC_MARKERS = re.compile(r"\bLO:|\bPL:|\bBL:|\bACS\b", re.I)
# A real street address: optional classification prefix ("RES "), then a
# house number + street name.
_STREET_ADDR_RE = re.compile(r"^(?:RES\s+)?(\d+\s+\S.+)$")
_TOOLTIP_SUFFIX_RE = re.compile(r"\s*\(\?\)\s*$")


def _clean_owner(s: str) -> str:
    return _TOOLTIP_SUFFIX_RE.sub("", s or "").strip()


def _split_location(loc: str) -> tuple[str | None, str | None]:
    """Return (street_address, legal_description) from the Property Location
    cell. Promote to street_address only when it reads like a real street
    address and carries no legal/plat marker."""
    loc = (loc or "").strip()
    if not loc:
        return None, None
    if not _LEGAL_DESC_MARKERS.search(loc):
        m = _STREET_ADDR_RE.match(loc)
        if m:
            return m.group(1).strip(), None
    return None, loc


def _parse_sale_date(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _find_data_table(html: str) -> str | None:
    """Return the HTML of the table whose header row is the real
    Owners-Name/Property-Location/Parcel-Number listing table, skipping the
    page's "contact-us-table" footer tables (same tag shape, different
    content) wherever they fall in document order."""
    for t in re.findall(r"<table.*?</table>", html, re.I | re.S):
        header = re.search(r"<tr[^>]*>(.*?)</tr>", t, re.I | re.S)
        if not header:
            continue
        header_text = re.sub(r"<[^>]+>", " ", header.group(1)).lower()
        if "owners name" in header_text and "property location" in header_text:
            return t
    return None


class CumberlandTaxForeclosure(BaseScraper):
    slug = "counties_nc.cumberland_tax_foreclosure"
    name = "Cumberland County NC Tax Foreclosures"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("cumberland_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        table = _find_data_table(html)
        if table is None:
            # No active-sale table posted right now (or the markup shifted
            # again) -- a clean zero, not a parse crash.
            log.info("cumberland_tax.done", count=0, reason="no_data_table")
            return out

        now = datetime.utcnow()
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 5:
                continue
            clean = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in cells]
            owner_raw, location, parcel, bill_number, sale_date_text = clean[0], clean[1], clean[2], clean[3], clean[4]

            if owner_raw.lower() == "owners name":
                continue  # header row

            owner = _clean_owner(owner_raw) or None
            street_address, legal_description = _split_location(location)
            sale_date = _parse_sale_date(sale_date_text)

            out.append(Listing(
                source=self.slug,
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county="Cumberland",
                parcel_id=parcel or None,
                defendant=owner,
                street_address=street_address,
                legal_description=legal_description,
                sale_date=sale_date,
                description=(f"Cumberland County tax foreclosure sale: {location}"
                             if location else "Cumberland County tax foreclosure sale"),
                first_seen=now,
                last_seen=now,
                raw={"cumberland_tax_foreclosure": {
                    "owner": owner,
                    "property_location": location,
                    "bill_number": bill_number or None,
                    "sale_date_raw": sale_date_text,
                    "cells": clean[:7],
                }},
            ))

        log.info("cumberland_tax.done", count=len(out))
        return out
