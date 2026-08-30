"""Lancaster County SC — Delinquent Tax properties.

Lancaster County posts delinquent properties scheduled for tax sale
at lancastercountysc.gov.  The county actively posts properties with
sale dates (confirmed: Sept 2026 sale with active postings).

Free, public, no login.
Slug: counties_sc.lancaster_delinquent_tax
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

PAGE_URL = "https://www.lancastercountysc.gov/AlertCenter.aspx?AID=A-Friendly-Reminder-The-Delinquent-Tax-C-16"


class LancasterDelinquentTax(BaseScraper):
    slug = "counties_sc.lancaster_delinquent_tax"
    name = "Lancaster County SC Delinquent Tax Sale"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True
    active_months = (8, 9, 10, 11, 12, 1)  # Lancaster posts earlier than most

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("lancaster_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        # Find PDF links to delinquent tax lists
        pdf_links = re.findall(r'href="([^"]*delinquent[^"]*\.pdf[^"]*)"', html, re.I)
        # Also look for property listing tables/divs
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)

        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if any(h in c.lower() for c in clean[:2] for h in ("owner", "name", "tms", "map", "#", "header")):
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
                source="counties_sc.lancaster_delinquent_tax",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Lancaster",
                parcel_id=parcel,
                defendant=owner,
                street_address=addr,
                description=" | ".join(clean[:6]) if clean else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"lancaster_delinquent_tax": {"cells": clean[:10]}},
            ))

        # If we found PDF links, record them in raw for follow-up
        if pdf_links and not out:
            for pdf_url in pdf_links[:5]:
                out.append(Listing(
                    source="counties_sc.lancaster_delinquent_tax",
                    source_url=pdf_url if pdf_url.startswith("http") else f"https://www.lancastercountysc.gov{pdf_url}",
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="Lancaster",
                    description=f"Delinquent tax list PDF: {pdf_url}",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"lancaster_delinquent_tax": {"pdf_url": pdf_url, "is_pdf_link": True}},
                ))

        log.info("lancaster_tax.done", count=len(out))
        return out
