"""Haywood County NC — Tax Foreclosure properties.

Haywood County publishes tax foreclosure properties at
haywoodcountync.gov/337.  The page lists properties going to tax sale
with owner names and parcel info.

Free, public, no login.
Slug: counties_nc.haywood_tax_foreclosures
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

PAGE_URL = "https://www.haywoodcountync.gov/337/Tax-Foreclosures"


class HaywoodTaxForeclosures(BaseScraper):
    slug = "counties_nc.haywood_tax_foreclosures"
    name = "Haywood County NC Tax Foreclosures"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("haywood_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if any(h in c.lower() for c in clean[:2] for h in ("owner", "name", "parcel", "pin", "address", "#")):
                continue

            parcel = None
            for c in clean:
                m = re.search(r"\b(\d{4,}[-\s]?[\d.]+)\b", c)
                if m:
                    parcel = m.group(1)
                    break

            owner = clean[0] if clean else None
            addr = None
            for c in clean:
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
                source="counties_nc.haywood_tax_foreclosures",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county="Haywood",
                parcel_id=parcel,
                defendant=owner,
                street_address=addr,
                judgment_amount=amount,
                description=" | ".join(clean[:8]) if clean else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"haywood_tax_foreclosures": {"cells": clean[:10]}},
            ))

        # PDF fallback
        if not out:
            pdf_links = re.findall(r'href="([^"]*(?:foreclos|tax|sale|auction)[^"]*\.pdf[^"]*)"', html, re.I)
            for pdf_url in pdf_links[:5]:
                full_url = urljoin(PAGE_URL, pdf_url)
                out.append(Listing(
                    source="counties_nc.haywood_tax_foreclosures",
                    source_url=full_url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Haywood",
                    description=f"Tax foreclosure PDF: {full_url}",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"haywood_tax_foreclosures": {"pdf_url": full_url, "is_pdf_link": True}},
                ))

        log.info("haywood_tax.done", count=len(out))
        return out
