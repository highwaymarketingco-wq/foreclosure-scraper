"""Sumter County SC — Surplus Property Sales.

Sumter County posts surplus property sales at
sumtercountysc.gov/online_services/property/surplus_sales.php.
These are county-owned properties being sold, including tax-delinquent
foreclosed properties that didn't sell at the annual tax sale.

Free, public, no login.
Slug: counties_sc.sumter_surplus
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

PAGE_URL = "https://www.sumtercountysc.gov/online_services/property/surplus_sales.php"


class SumterSurplusSales(BaseScraper):
    slug = "counties_sc.sumter_surplus"
    name = "Sumter County SC Surplus Property Sales"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("sumter_surplus.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)

        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if any(h in c.lower() for c in clean[:2] for h in ("owner", "name", "tms", "map", "parcel", "#")):
                continue
            # FOUND 2026-09-15 (background triage agent): this loop had NO
            # digit-presence requirement at all (unlike the near-identical
            # loops in marlboro_delinquent_tax.py / clarendon_tax_auction.py,
            # which both gate on `any(re.search(r"\d", c) for c in clean)`).
            # Confirmed live: it was grabbing the page's SIDEBAR NAVIGATION
            # table (2-column, no digits anywhere -- links like "Sheriff's
            # Office" / "Seized/Unclaimed Property" / "Detention Center
            # Volunteer Inmate Items") and emitting each row as a fake
            # surplus-property listing with every real field null.
            if not any(re.search(r"\d", c) for c in clean):
                continue

            parcel = None
            for c in clean:
                m = re.search(r"\b(\d{3}[-\s]?\d{2}[-\s]?\d{2}[-\s]?[\d.]+)\b", c)
                if m:
                    parcel = m.group(1)
                    break

            owner = clean[0] if clean else None
            addr = None
            for c in clean[1:]:
                if re.search(r"\d+\s+\w+", c):
                    addr = c
                    break

            amount = None
            for c in clean:
                m = re.search(r"\$[\d,]+", c)
                if m:
                    try:
                        amount = float(m.group().replace("$", "").replace(",", ""))
                    except ValueError:
                        pass

            out.append(Listing(
                source="counties_sc.sumter_surplus",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Sumter",
                parcel_id=parcel,
                defendant=owner,
                street_address=addr,
                opening_bid=amount,
                description=" | ".join(clean[:6]) if clean else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sumter_surplus": {"cells": clean[:10]}},
            ))

        # <li>-fallback REMOVED 2026-09-15. Even after adding the same
        # digit-presence guard as the table loop above, live re-verification
        # still produced garbage from it -- one row was literal page
        # JAVASCRIPT (a calendar-widget snippet, "var defaultCalendarColor
        # = ..."), matched because it happened to contain the digit "8" and
        # the substring "sale"/"bid" somewhere in the surrounding script.
        # A keyword-plus-digit match on arbitrary page text is not a safe
        # enough signal to build a listing from -- the fixed table loop
        # above (which requires an actual <table> row shape, not just
        # keyword-and-digit-bearing text anywhere on the page) is kept;
        # this looser fallback is not.

        log.info("sumter_surplus.done", count=len(out))
        return out
