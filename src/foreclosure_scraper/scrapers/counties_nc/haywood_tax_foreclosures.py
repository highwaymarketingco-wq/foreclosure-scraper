"""Haywood County NC — Tax Foreclosure properties.

Haywood County explains its tax-foreclosure process at
haywoodcountync.gov/337, but the actual sale notices are published in the
CivicPlus Bids module under the "Tax Foreclosures" category (CatID 17),
linked from that page as "Notice of Tax Foreclosure Sales".  Each posting
carries the sale date and a DocumentCenter link to the scanned notice PDF;
owner/parcel/address come from the document-OCR enricher.

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

# 2026-09-09: /337/Tax-Foreclosures is purely procedural prose (how in-rem vs
# mortgage-style sales work, upset-bid rules).  It has no <table> and no PDF
# links, so the table parse below has always returned 0.  The actual sale
# notices live behind the page's own "Notice of Tax Foreclosure Sales" link,
# in the CivicPlus Bids module under the "Tax Foreclosures" category (CatID 17).
BIDS_URL = (
    "https://www.haywoodcountync.gov/Bids.aspx"
    "?CatID=17&txtSort=Category&showAllBids=&Status=open"
)

# One posting per notice: <div class="listItemsRow bid ..."> ... </div>.
# Split on the row marker rather than matching balanced </div>s, so a change
# in CivicPlus nesting depth does not silently zero the parse.
_ROW_SPLIT_RE = re.compile(r'<div class="listItemsRow bid[^"]*">', re.I)
_ITEMS_START_RE = re.compile(r'<div class="bidItems listItems">', re.I)


def _strip_tags(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


def _bid_blocks(html: str) -> list[str]:
    """Return the HTML fragment for each bid posting row."""
    m = _ITEMS_START_RE.search(html)
    section = html[m.end():] if m else html
    # Everything after the postings container is page chrome / scripts.
    cut = re.search(r"<script\b", section, re.I)
    if cut:
        section = section[: cut.start()]
    return _ROW_SPLIT_RE.split(section)[1:]


def _parse_bid_rows(html: str) -> list[Listing]:
    """Parse the Tax Foreclosures bid postings into Listings.

    Each posting carries a title (which states the sale date/time), a
    DocumentCenter path to the scanned notice PDF, and a closing date.
    The PDFs are scanned images, so owner/parcel/address come from the
    document-OCR enricher — the row is emitted with is_pdf_link=True the
    same way the other PDF-notice county scrapers do it.
    """
    out: list[Listing] = []
    seen: set[str] = set()
    for block in _bid_blocks(html):
        title_m = re.search(
            r'<div class="bidTitle".*?</div>', block, re.I | re.S
        )
        title_block = title_m.group(0) if title_m else block
        spans = [
            _strip_tags(s)
            for s in re.findall(r"<span[^>]*>(.*?)</span>", title_block, re.I | re.S)
        ]
        spans = [s for s in spans if s]
        title = spans[0] if spans else None

        doc_path = None
        for s in spans:
            if "/DocumentCenter/View/" in s:
                doc_path = s
                break
        if doc_path is None:
            m = re.search(r"(/DocumentCenter/View/\d+[^\s\"'<>]*)", block, re.I)
            doc_path = m.group(1) if m else None

        detail_m = re.search(r'href="(bids\.aspx\?bidID=\d+)"', block, re.I)
        detail_url = (
            urljoin(BIDS_URL, detail_m.group(1)) if detail_m else BIDS_URL
        )
        pdf_url = urljoin(BIDS_URL, doc_path) if doc_path else None

        status_m = re.search(r'<div class="bidStatus".*', block, re.I | re.S)
        status_txt = _strip_tags(status_m.group(0))[:200] if status_m else ""

        sale_date = None
        for text in (title or "", status_txt):
            m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
            if m:
                try:
                    sale_date = datetime(
                        int(m.group(3)), int(m.group(1)), int(m.group(2))
                    )
                    break
                except ValueError:
                    pass
            m = re.search(
                r"\b(January|February|March|April|May|June|July|August|"
                r"September|October|November|December)\s+(\d{1,2})[,\s]+(\d{4})\b",
                text,
                re.I,
            )
            if m:
                try:
                    sale_date = datetime.strptime(
                        f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y"
                    )
                    break
                except ValueError:
                    pass

        key = pdf_url or detail_url
        if not key or key in seen:
            continue
        seen.add(key)

        out.append(Listing(
            source="counties_nc.haywood_tax_foreclosures",
            source_url=pdf_url or detail_url,
            listing_type=ListingType.TAX_SALE,
            property_kind=PropertyKind.UNKNOWN,
            state="NC",
            county="Haywood",
            sale_date=sale_date,
            description=title or f"Haywood County tax foreclosure notice: {key}",
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"haywood_tax_foreclosures": {
                "pdf_url": pdf_url,
                "is_pdf_link": bool(pdf_url),
                "bid_detail_url": detail_url,
                "title": title,
                "status": status_txt or None,
            }},
        ))
    return out


class HaywoodTaxForeclosures(BaseScraper):
    slug = "counties_nc.haywood_tax_foreclosures"
    name = "Haywood County NC Tax Foreclosures"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []

        # Primary lane: the Bids-module postings, which is where the actual
        # sale notices are published.
        try:
            bids_html = await get_text(BIDS_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("haywood_tax.bids_fetch_fail", error=str(exc)[:160])
        else:
            if bids_html and len(bids_html) >= 200:
                out.extend(_parse_bid_rows(bids_html))
        if out:
            log.info("haywood_tax.done", count=len(out), lane="bids")
            return out

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
