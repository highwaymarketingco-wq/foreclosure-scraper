"""Chester County SC - Delinquent Tax Sale properties.

Chester County publishes delinquent tax sale properties on its county
website. The page lists parcels scheduled for tax sale with owner names,
TMS numbers, and property addresses.

Free, public, no login.
Slug: counties_sc.chester_delinquent_tax
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

PAGE_URL = "https://www.chestercountysc.gov/treasurer/delinquent-tax-sale"


class ChesterDelinquentTax(BaseScraper):
    slug = "counties_sc.chester_delinquent_tax"
    name = "Chester County SC Delinquent Tax Sale"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True
    active_months = (10, 11, 12, 1)

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        html = None
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("chester_tax.fetch_fail", error=str(exc)[:160])
        if not html or len(html) < 200:
            # Fallback: StealthyFetcher (real headless browser)
            try:
                from scrapling.fetchers import StealthyFetcher
                log.info("chester_tax.fallback_browser", url=PAGE_URL)
                page = await StealthyFetcher.async_fetch(PAGE_URL, timeout=60)
                html = page.html if hasattr(page, "html") else str(page)
            except Exception as exc2:
                log.warning("chester_tax.browser_fail", error=str(exc2)[:160])
                return out
        if not html or len(html) < 200:
            return out

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

            out.append(Listing(
                source="counties_sc.chester_delinquent_tax",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Chester",
                parcel_id=parcel,
                defendant=owner,
                street_address=addr,
                description=" | ".join(clean[:6]),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"chester_delinquent_tax": {"cells": clean[:10]}},
            ))

        log.info("chester_tax.done", count=len(out))
        return out
