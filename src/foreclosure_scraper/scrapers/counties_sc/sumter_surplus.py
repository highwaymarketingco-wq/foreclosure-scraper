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

        # Fallback: look for list items with property info
        if not out:
            items = re.findall(r'<li[^>]*>(.*?)</li>', html, re.I | re.S)
            for item in items:
                text = re.sub(r"<[^>]+>", "", item).strip()
                if len(text) < 10:
                    continue
                if not any(kw in text.lower() for kw in ("parcel", "tms", "map", "pin", "sale", "bid", "foreclos")):
                    continue
                out.append(Listing(
                    source="counties_sc.sumter_surplus",
                    source_url=PAGE_URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="Sumter",
                    description=text[:300],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"sumter_surplus": {"text": text[:200]}},
                ))

        log.info("sumter_surplus.done", count=len(out))
        return out
