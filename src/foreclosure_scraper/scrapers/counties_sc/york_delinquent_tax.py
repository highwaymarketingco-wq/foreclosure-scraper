"""York County SC — Tax Collection / Delinquent Tax properties.

York County posts delinquent tax information at
yorkcountysc.gov/216.  The page lists properties with delinquent taxes
heading to the annual tax sale.

Free, public, no login.
Slug: counties_sc.york_delinquent_tax
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

PAGE_URL = "https://www.yorkcountysc.gov/216/Tax-Collection"


class YorkDelinquentTax(BaseScraper):
    slug = "counties_sc.york_delinquent_tax"
    name = "York County SC Delinquent Tax Collection"
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
            log.warning("york_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        # York County uses CivicPlus CMS — look for property listings in tables
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

            out.append(Listing(
                source="counties_sc.york_delinquent_tax",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="York",
                parcel_id=parcel,
                defendant=owner,
                street_address=addr,
                description=" | ".join(clean[:6]) if clean else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"york_delinquent_tax": {"cells": clean[:10]}},
            ))

        # Look for PDF links to tax sale lists
        if not out:
            pdf_links = re.findall(r'href="([^"]*(?:tax|delinquent|sale)[^"]*\.pdf[^"]*)"', html, re.I)
            for pdf_url in pdf_links[:5]:
                full_url = pdf_url if pdf_url.startswith("http") else f"https://www.yorkcountysc.gov{pdf_url}"
                out.append(Listing(
                    source="counties_sc.york_delinquent_tax",
                    source_url=full_url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="York",
                    description=f"Delinquent tax list PDF: {pdf_url}",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"york_delinquent_tax": {"pdf_url": pdf_url, "is_pdf_link": True}},
                ))

        log.info("york_tax.done", count=len(out))
        return out
