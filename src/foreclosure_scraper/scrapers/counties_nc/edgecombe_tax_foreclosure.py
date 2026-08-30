"""Edgecombe County NC - Tax Foreclosure properties.

Edgecombe County publishes tax foreclosure properties on its county
website. Properties with delinquent taxes being processed for sale.

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


class EdgecombeTaxForeclosure(BaseScraper):
    slug = "counties_nc.edgecombe_tax_foreclosure"
    name = "Edgecombe County NC Tax Foreclosures"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True
    active_months = (1, 2, 3, 4, 5, 6, 7, 8)

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("edgecombe_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if any(h in c.lower() for c in clean[:2] for h in ("owner", "name", "parcel", "pin", "#", "account")):
                continue
            if not any(re.search(r"\d", c) for c in clean):
                continue

            parcel = None
            for c in clean:
                m = re.search(r"\b(\d{4,}[-\s]?\d{2,}[-\s]?\d{2,}[-\s]?[\d.]+)\b", c)
                if m:
                    parcel = m.group(1).strip()
                    break
                m = re.search(r"\b(\d{6,})\b", c)
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

            amount = None
            for c in clean:
                m = re.search(r"\$[\d,]+\.?\d*", c)
                if m:
                    amt_str = m.group(0).replace("$", "").replace(",", "")
                    try:
                        amount = float(amt_str)
                    except ValueError:
                        pass
                    break

            out.append(Listing(
                source="counties_nc.edgecombe_tax_foreclosure",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county="Edgecombe",
                parcel_id=parcel,
                defendant=owner,
                street_address=addr,
                judgment_amount=amount,
                description=" | ".join(clean[:6]),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"edgecombe_tax_foreclosure": {"cells": clean[:10]}},
            ))

        log.info("edgecombe_tax.done", count=len(out))
        return out
