"""Darlington County SC - Delinquent Tax Sale properties.

Darlington County publishes delinquent tax sale properties on its county
website. Annual tax sale lists with owner names, TMS numbers, addresses,
and bid amounts.

Free, public, no login.
Slug: counties_sc.darlington_delinquent_tax
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

#: Weekday names, so the county's office-hours table can never be parsed as leads.
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
             "sunday", "days", "hours")

PAGE_URL = "https://www.darcosc.com/government/treasurer/index.php"


def parse_rows(html: str) -> list[Listing]:
    """Parse the treasurer page's tables into Listings.

    Module-level and pure so the junk-row guards are TESTABLE without a network
    fetch. They were previously inline in fetch(), which is why the office-hours
    hazard sat there unnoticed: nothing could exercise it.
    """
    out: list[Listing] = []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
        if len(cells) < 2:
            continue
        clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if any(h in c.lower() for c in clean[:2] for h in ("owner", "name", "tms", "map", "#")):
            continue
        if not any(re.search(r"\d", c) for c in clean):
            continue
        # The page's OFFICE-HOURS table is also a <table> of <tr>. Its rows pass
        # both filters above -- "Monday" is not in the header skip list and
        # "8:30 a.m. - 5:00 p.m." satisfies the digit test -- so this parser was
        # one populated hours cell away from emitting
        # defendant='Monday' street_address='8:30 a.m. - 5:00 p.m.' as a TAX_SALE
        # lead. It returns 0 today only because those cells happen to be empty.
        if any(d in c.lower() for c in clean[:2] for d in _WEEKDAYS):
            continue

        parcel = None
        for c in clean:
            m = re.search(r"\b(\d{3}[-\s]?\d{2}[-\s]?\d{2}[-\s]?[\d.]+)\b", c)
            if m:
                parcel = m.group(1).strip()
                break
            m = re.search(r"\b(\d{8,})\b", c)
            if m and not parcel:
                parcel = m.group(1)

        owner = clean[0] if clean else None
        addr = None
        for c in clean[1:]:
            if re.search(r"\d+\s+\w+", c):
                addr = c
                break
        if not addr and len(clean) > 1:
            addr = clean[1] if len(clean[1]) > 5 else None

        # A delinquent-tax row with no TMS is not a workable lead: it cannot be
        # underwritten, joined to the assessor, or routed. Requiring the parcel is
        # what actually closes the junk-row class, rather than relying on
        # _active_only() to delete dateless rows as an accidental last line of
        # defence -- which is exactly the guard that disappeared when this slug
        # was added to DATELESS_OK_SOURCES.
        if not parcel:
            continue

        out.append(Listing(
            source="counties_sc.darlington_delinquent_tax",
            source_url=PAGE_URL,
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="SC",
            county="Darlington",
            parcel_id=parcel,
            defendant=owner,
            street_address=addr,
            description=" | ".join(clean[:6]),
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"darlington_delinquent_tax": {"cells": clean[:10]}},
        ))
    return out


class DarlingtonDelinquentTax(BaseScraper):
    slug = "counties_sc.darlington_delinquent_tax"
    name = "Darlington County SC Delinquent Tax Sale"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True
    active_months = (10, 11, 12, 1)

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("darlington_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        out = parse_rows(html)
        log.info("darlington_tax.done", count=len(out))
        return out
