"""Laurens County SC - Delinquent Tax Sale properties.

Laurens County publishes delinquent tax sale properties on its county
website. Annual tax sale lists with owner names, TMS numbers, addresses.

Free, public, no login.
Slug: counties_sc.laurens_delinquent_tax
Category: county_tax
ListingType: TAX_SALE

2026-09-28 re-verification (MASTER_GAPS had this flagged 404/CMS-migration):
PAGE_URL below is live -- clean HTTP 200, ~84KB, matches the URL a re-probe
pass pointed at. BUT the page (Revize CMS) no longer carries an HTML table
of parcels at all (0 <table> tags). Its own in-page "Current FLC List" and
"Tax Sale Overage List" links are BROKEN (point at .../error.html on the
county's own site). The one working document link, "Delinquent Tax Notice
of Properties," goes to a newstogo.us scanned-newspaper page-flip viewer
(JS "booklet" reader over raster images) -- not text-parseable without OCR
and a headless browser, so there is nothing this HTML-table parser can
recover here; the 0-row result below is a correct read of an empty page,
not a parser bug.

The REAL per-parcel Laurens delinquent-tax roll -- owner, address, TMS,
amount owed, tax year -- is already live elsewhere: this same page's
"Pay Taxes Online" flow points at laurenstreasurer.qpaybill.com, which
`counties_sc.qpaybill_delinquent_roll` already covers (COUNTIES["Laurens"]
= "laurenstreasurer", verified live 2026-09-10). Re-confirmed live again
2026-09-28 with a single-prefix smoke test ("S") returning 25 real 2025
rows with dollar amounts (e.g. SAAYU INVESTMENT LLC, 906-16-01-070,
$1,719.49 unpaid). Do not duplicate that sweep here -- this module is kept
only in case the county ever republishes a table on this page.

RE-VERIFIED LIVE 2026-10-04 (extraction-completeness audit): still holds,
unchanged. The page still has 0 `<table>` tags; its only two document-ish
links are "Delinquent Tax Sale Registration Packet" and "Delinquent Tax Sale
Bidder Registration Form" (procedure paperwork, not a property list) plus
the same newstogo.us scanned-newspaper page-flip viewer link noted below --
no new PDF, no "Current FLC List"/"Tax Sale Overage List" link exists on
this page at all (those were a DIFFERENT county's dead links, not Laurens').
qpaybill's Laurens tenant is still delivering: live-swept prefix "S" again
today, 72 real current rows including the SAME SAAYU INVESTMENT LLC parcel
(906-16-01-070, now $1,719.49 for tax year 2025 specifically -- i.e. still
unpaid, not a one-off).
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

PAGE_URL = "https://www.laurenscountysc.gov/departments/treasurer/delinquent_taxes.php"


class LaurensDelinquentTax(BaseScraper):
    slug = "counties_sc.laurens_delinquent_tax"
    name = "Laurens County SC Delinquent Tax Sale"
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
            log.warning("laurens_tax.fetch_fail", error=str(exc)[:160])
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
                source="counties_sc.laurens_delinquent_tax",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Laurens",
                parcel_id=parcel,
                defendant=owner,
                street_address=addr,
                description=" | ".join(clean[:6]),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"laurens_delinquent_tax": {"cells": clean[:10]}},
            ))

        log.info("laurens_tax.done", count=len(out))
        return out
