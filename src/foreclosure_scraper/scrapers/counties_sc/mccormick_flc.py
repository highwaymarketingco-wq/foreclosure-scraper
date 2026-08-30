"""McCormick County SC - Forfeited Land Commission (FLC) properties.

McCormick County's FLC page lists available forfeited land commission
properties - properties the county acquired through tax delinquency
proceedings. These are county-owned properties available for purchase.

Free, public, no login.
Slug: counties_sc.mccormick_flc
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

PAGE_URL = "https://www.mccormickcountysc.org/departments/treasurer.php"


class McCormickFLC(BaseScraper):
    slug = "counties_sc.mccormick_flc"
    name = "McCormick County SC Forfeited Land Commission"
    category = "county_tax"
    timeout_s = 90.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("mccormick_flc.fetch_fail", error=str(exc)[:160])
            return out

        if not html:
            return out

        # Find PDF links to property lists
        pdf_links = re.findall(r'href="([^"]*\.pdf[^"]*)"', html, re.I)
        # Find TMS/parcel numbers and addresses in the HTML
        parcels = re.findall(r"(?:TMS|PIN|Parcel)\s*:?\s*([\d\-\.]+)", html, re.I)
        addresses = re.findall(
            r"\b(\d+\s+[A-Za-z0-9\s]+(?:St|Ave|Rd|Dr|Ln|Ct|Blvd|Hwy|Way|Cir|Trl|Pkwy|Ter)[A-Za-z\s]*)",
            html,
        )

        if not parcels and not addresses:
            # Try table parsing
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
            for row in rows:
                cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
                if len(cells) < 2:
                    continue
                clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
                if not any(re.search(r"\d", c) for c in clean):
                    continue
                parcel = None
                for c in clean:
                    m = re.search(r"\b(\d{3}[-\s]?\d{2}[-\s]?\d{2}[-\s]?[\d.]+)\b", c)
                    if m:
                        parcel = m.group(1)
                        break
                out.append(Listing(
                    source="counties_sc.mccormick_flc",
                    source_url=PAGE_URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="McCormick",
                    parcel_id=parcel,
                    defendant=clean[0] if clean else None,
                    street_address=clean[1] if len(clean) > 1 else None,
                    description=" | ".join(clean[:6]),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"mccormick_flc": {"cells": clean[:10], "pdf_links": pdf_links[:3]}},
                ))
        else:
            max_items = max(len(parcels), len(addresses), 1)
            for i in range(max_items):
                parcel = parcels[i] if i < len(parcels) else None
                addr = addresses[i].strip() if i < len(addresses) else None
                out.append(Listing(
                    source="counties_sc.mccormick_flc",
                    source_url=PAGE_URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="McCormick",
                    parcel_id=parcel,
                    street_address=addr,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"mccormick_flc": {"pdf_links": pdf_links[:3]}},
                ))

        log.info("mccormick_flc.done", count=len(out))
        return out
