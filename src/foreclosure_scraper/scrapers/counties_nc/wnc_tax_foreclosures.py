"""Western NC multi-county — Tax foreclosure / delinquent tax pages.

Several small Western NC counties publish tax foreclosure and delinquent
tax sale information on their county websites but don't warrant individual
scraper modules due to low volume.  This scraper covers them all:

- Watauga County (wataugacounty.org)
- Avery County (averycounty.com)
- Yancey County (yanceycountync.gov)
- Cherokee NC County (cherokeecounty-nc.gov)
- Madison County (madisoncountync.gov)

Each county page is checked for property listings, PDF links to tax sale
lists, and delinquent tax information.

Free, public, no login.
Slug: counties_nc.wnc_tax_foreclosures
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_bytes, get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

COUNTIES: dict[str, str] = {
    "Watauga": "https://www.wataugacounty.org/",
    "Avery": "https://www.averycounty.com/",
    "Yancey": "https://www.yanceycountync.gov/",
    "Cherokee": "https://www.cherokeecounty-nc.gov/",
    "Madison": "https://www.madisoncountync.gov/",
}


def _pdf_text(data: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:
        return ""


class WNCTaxForeclosures(BaseScraper):
    slug = "counties_nc.wnc_tax_foreclosures"
    name = "Western NC Multi-County Tax Foreclosures"
    category = "county_tax"
    timeout_s = 180.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []

        for county, base_url in COUNTIES.items():
            try:
                html = await get_text(base_url, impersonate=True, timeout=40.0)
            except Exception as exc:
                log.warning("wnc_tax.fetch_fail", county=county, error=str(exc)[:160])
                continue

            if not html or len(html) < 200:
                continue

            # Find tax/foreclosure/sale related links
            links = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.I | re.S)
            tax_links: list[tuple[str, str]] = []
            for href, text in links:
                low = (href + " " + re.sub(r"<[^>]+>", "", text)).lower()
                if any(kw in low for kw in ("tax", "foreclos", "delinquent", "sale", "auction", "sheriff", "bid", "treasurer", "collector")):
                    tax_links.append((urljoin(base_url, href), re.sub(r"<[^>]+>", "", text).strip()))

            # Follow tax-related links and parse
            for tax_url, link_text in tax_links[:3]:
                if tax_url == base_url:
                    continue
                try:
                    sub_html = await get_text(tax_url, impersonate=True, timeout=40.0)
                except Exception:
                    continue
                if not sub_html:
                    continue

                # Parse table rows
                rows = re.findall(r"<tr[^>]*>(.*?)</tr>", sub_html, re.I | re.S)
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
                    for c in clean[1:]:
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
                        source="counties_nc.wnc_tax_foreclosures",
                        source_url=tax_url,
                        listing_type=ListingType.TAX_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        state="NC",
                        county=county,
                        parcel_id=parcel,
                        defendant=owner,
                        street_address=addr,
                        judgment_amount=amount,
                        description=" | ".join(clean[:8]) if clean else None,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"wnc_tax_foreclosures": {"county": county, "cells": clean[:10], "source_link": link_text}},
                    ))

                # Check for PDF links
                pdf_links = re.findall(r'href="([^"]*\.pdf[^"]*)"', sub_html, re.I)
                for pdf_url in pdf_links[:3]:
                    full_url = urljoin(tax_url, pdf_url)
                    # Try to download and parse PDF
                    try:
                        data = await get_bytes(full_url, timeout=60.0)
                    except Exception:
                        continue
                    if not data or data[:4] != b"%PDF":
                        continue
                    text = _pdf_text(data)
                    if not text:
                        continue
                    for line in text.splitlines():
                        line = line.strip()
                        if len(line) < 10:
                            continue
                        if any(h in line.lower() for h in ("notice", "page ", "county tax")):
                            continue
                        parcel = None
                        m = re.search(r"\b(\d{4,}[-\s]?[\d.]+)\b", line)
                        if m:
                            parcel = m.group(1)
                        addr = None
                        m = re.search(r"\d+\s+\w+[\w\s]+", line)
                        if m:
                            addr = m.group().strip()
                        if not parcel and not addr:
                            continue
                        out.append(Listing(
                            source="counties_nc.wnc_tax_foreclosures",
                            source_url=full_url,
                            listing_type=ListingType.TAX_SALE,
                            property_kind=PropertyKind.UNKNOWN,
                            state="NC",
                            county=county,
                            parcel_id=parcel,
                            street_address=addr,
                            description=line[:300],
                            first_seen=datetime.utcnow(),
                            last_seen=datetime.utcnow(),
                            raw={"wnc_tax_foreclosures": {"county": county, "pdf_url": full_url, "line": line[:200]}},
                        ))

        log.info("wnc_tax.done", count=len(out))
        return out
