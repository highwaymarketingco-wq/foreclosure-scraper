"""Aiken County SC — Delinquent Tax Sale properties.

Aiken County publishes delinquent tax sale properties at
sc-aikencounty.civicplus.com/309.  The page lists parcels scheduled
for the annual tax sale with owner names, TMS numbers, and property
descriptions/addresses.

CivicPlus is a widely-used CMS for SC counties — this scraper pattern
can be reused for other CivicPlus counties.

Free, public, no login.
Slug: counties_sc.aiken_delinquent_tax
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://sc-aikencounty.civicplus.com/309/Tax-Foreclosures"


class AikenDelinquentTax(BaseScraper):
    slug = "counties_sc.aiken_delinquent_tax"
    name = "Aiken County SC Delinquent Tax Sale"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True
    active_months = (10, 11, 12, 1)  # SC tax sales run Nov-Jan

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("aiken_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        # CivicPlus pages use either tables or list elements
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        if not rows:
            rows = re.findall(r'<div[^>]*class="[^"]*(?:listing|property|parcel)[^"]*"[^>]*>(.*?)</div>', html, re.I | re.S)

        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            # Skip header rows
            if any(h in c.lower() for c in clean[:2] for h in ("owner", "name", "tms", "map", "#")):
                continue
            if not any(re.search(r"\d", c) for c in clean):
                continue

            # Try to extract TMS/parcel number
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
                if re.search(r"\d+\s+\w+", c) and not c.replace(".", "").replace(",", "").replace("$", "").isdigit():
                    addr = c
                    break
            if not addr and len(clean) > 1:
                addr = clean[1] if len(clean[1]) > 5 else None

            desc = " | ".join(clean)[:6] if clean else None

            out.append(Listing(
                source="counties_sc.aiken_delinquent_tax",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Aiken",
                parcel_id=parcel,
                defendant=owner,
                street_address=addr,
                description=desc,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"aiken_delinquent_tax": {"cells": clean[:10]}},
            ))

        log.info("aiken_tax.done", count=len(out))
        return out
