"""Clarendon County SC — Treasurer Auction properties.

Clarendon County treasurer posts properties for auction at
clarendoncountysc.gov.  The county website features an auction hammer
icon linking to delinquent tax sale properties.

Free, public, no login.
Slug: counties_sc.clarendon_tax_auction
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

PAGE_URL = "https://www.clarendoncountysc.gov/"


class ClarendonTaxAuction(BaseScraper):
    slug = "counties_sc.clarendon_tax_auction"
    name = "Clarendon County SC Tax Auction Properties"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True
    active_months = (9, 10, 11, 12, 1)

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("clarendon_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        # Find auction/tax sale links
        links = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.I | re.S)
        auction_links: list[tuple[str, str]] = []
        for href, text in links:
            low = (href + text).lower()
            if any(kw in low for kw in ("auction", "tax sale", "delinquent", "foreclos", "sheriff", "treasurer", "bid")):
                auction_links.append((urljoin(PAGE_URL, href), re.sub(r"<[^>]+>", "", text).strip()))

        # Follow auction links and parse property data
        for auction_url, link_text in auction_links[:5]:
            if auction_url == PAGE_URL:
                continue
            try:
                sub_html = await get_text(auction_url, impersonate=True, timeout=40.0)
            except Exception:
                continue
            if not sub_html:
                continue

            # Parse property listings
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
                    source="counties_sc.clarendon_tax_auction",
                    source_url=auction_url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="Clarendon",
                    parcel_id=parcel,
                    defendant=owner,
                    street_address=addr,
                    description=" | ".join(clean[:6]) if clean else None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"clarendon_tax_auction": {"cells": clean[:10], "source_link": link_text}},
                ))

            # Also check for PDF links on auction pages
            pdf_links = re.findall(r'href="([^"]*\.pdf[^"]*)"', sub_html, re.I)
            for pdf_url in pdf_links[:3]:
                full_url = urljoin(auction_url, pdf_url)
                out.append(Listing(
                    source="counties_sc.clarendon_tax_auction",
                    source_url=full_url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="Clarendon",
                    description=f"Tax auction PDF: {full_url}",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"clarendon_tax_auction": {"pdf_url": full_url, "is_pdf_link": True}},
                ))

        log.info("clarendon_tax.done", count=len(out))
        return out
