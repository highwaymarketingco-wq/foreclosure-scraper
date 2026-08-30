"""Wake County NC - Tax Foreclosure properties.

Wake County publishes tax foreclosure properties at wake.gov. The page
has tabs by municipality with property-level data: Tax ID, amount due,
address, sale dates. Links to property records at services.wake.gov.

Free, public, no login.
Slug: counties_nc.wake_tax_foreclosure
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

PAGE_URL = "https://www.wake.gov/departments-government/tax-administration/real-estate/foreclosures"


class WakeTaxForeclosure(BaseScraper):
    slug = "counties_nc.wake_tax_foreclosure"
    name = "Wake County NC Tax Foreclosures"
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
            log.warning("wake_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        # Wake uses JS-rendered tabs but the property data is in the HTML
        # Look for property entries with Tax IDs, addresses, amounts
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if any(h in c.lower() for c in clean[:2] for h in ("owner", "name", "tax id", "parcel", "account", "#")):
                continue
            if not any(re.search(r"\d", c) for c in clean):
                continue

            # Wake County Tax IDs are typically numeric (REID)
            parcel = None
            for c in clean:
                m = re.search(r"\b(\d{6,})\b", c)
                if m:
                    parcel = m.group(1)
                    break

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

            # Extract property record links
            record_url = None
            link_match = re.search(r'href="(https://services\.wake\.gov/realestate/Account\.asp\?id=\d+)"', row, re.I)
            if link_match:
                record_url = link_match.group(1)

            out.append(Listing(
                source="counties_nc.wake_tax_foreclosure",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county="Wake",
                parcel_id=parcel,
                defendant=owner,
                street_address=addr,
                judgment_amount=amount,
                description=" | ".join(clean[:6]),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"wake_tax_foreclosure": {"cells": clean[:10], "record_url": record_url}},
            ))

        # Also look for linked PDFs with property lists
        pdf_links = re.findall(r'href="([^"]*forecl[^"]*\.pdf[^"]*)"', html, re.I)
        if pdf_links and not out:
            log.info("wake_tax.pdf_found", pdfs=len(pdf_links))

        log.info("wake_tax.done", count=len(out))
        return out
