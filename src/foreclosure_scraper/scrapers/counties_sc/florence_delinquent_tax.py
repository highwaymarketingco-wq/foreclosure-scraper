"""Florence County SC — Tax Foreclosure / Delinquent Tax info.

Florence County posts delinquent tax information at florenceco.org.
The page links to current-year tax sale properties and auction info.

Free, public, no login.
Slug: counties_sc.florence_delinquent_tax
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

PAGE_URL = "https://www.florenceco.org/"


class FlorenceDelinquentTax(BaseScraper):
    slug = "counties_sc.florence_delinquent_tax"
    name = "Florence County SC Delinquent Tax Sale"
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
            log.warning("florence_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        # Find tax/delinquent/sale links
        links = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.I | re.S)
        tax_links: list[tuple[str, str]] = []
        for href, text in links:
            low = (href + " " + re.sub(r"<[^>]+>", "", text)).lower()
            if any(kw in low for kw in ("tax", "delinquent", "sale", "auction", "foreclos", "bid", "sheriff", "treasurer")):
                tax_links.append((urljoin(PAGE_URL, href), re.sub(r"<[^>]+>", "", text).strip()))

        # Follow tax sale links
        for tax_url, link_text in tax_links[:5]:
            if tax_url == PAGE_URL:
                continue
            try:
                sub_html = await get_text(tax_url, impersonate=True, timeout=40.0)
            except Exception:
                continue
            if not sub_html:
                continue

            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", sub_html, re.I | re.S)
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
                    source="counties_sc.florence_delinquent_tax",
                    source_url=tax_url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="Florence",
                    parcel_id=parcel,
                    defendant=owner,
                    street_address=addr,
                    description=" | ".join(clean[:6]) if clean else None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"florence_delinquent_tax": {"cells": clean[:10], "source_link": link_text}},
                ))

            # Check for PDF links
            pdf_links = re.findall(r'href="([^"]*\.pdf[^"]*)"', sub_html, re.I)
            for pdf_url in pdf_links[:3]:
                full_url = urljoin(tax_url, pdf_url)
                out.append(Listing(
                    source="counties_sc.florence_delinquent_tax",
                    source_url=full_url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="Florence",
                    description=f"Tax sale PDF: {full_url}",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"florence_delinquent_tax": {"pdf_url": full_url, "is_pdf_link": True}},
                ))

        log.info("florence_tax.done", count=len(out))
        return out
