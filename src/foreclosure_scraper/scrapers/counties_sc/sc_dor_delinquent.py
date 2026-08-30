"""SC Department of Revenue — Delinquent Taxpayers list.

The SC DOR publishes a public list of delinquent taxpayers (individual +
business) at mydorway.dor.sc.gov.  This is a state-level tax-lien distress
signal: the taxpayer owes back state taxes and DOR has filed a lien.

Data shape: HTML table rendered behind a MyDORWAY JS portal.  The page
exposes a grid (role="grid") with rows containing taxpayer name, account
number, liability amount, and filing date.  Some columns are unstructured
free-text, so we extract what we reliably can (name, amount, date) and
leave the rest in raw.

Free, public data — no login, no payment.  The portal uses ASP.NET-style
postbacks for pagination; we fetch the first page and parse what's visible.
If the portal adds server-side rendering or blocks plain httpx, we fall
back to impersonate=True (stealth browser headers).

Slug: counties_sc.sc_dor_delinquent_taxpayers
Category: state_tax
ListingType: TAX_LIEN (state tax debt, not a county property tax sale)
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

PAGE_URL = "https://mydorway.dor.sc.gov/?link=delinquentind"

# Patterns for extracting data from table rows
_NAME_RE = re.compile(r"<td[^>]*>\s*([^<]+)", re.I)
_AMT_RE = re.compile(r"\$[\d,]+\.?\d*", re.I)
_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})")


class SCDORDelinquentTaxpayers(BaseScraper):
    slug = "counties_sc.sc_dor_delinquent_taxpayers"
    name = "SC DOR Delinquent Taxpayers"
    category = "state_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("sc_dor_delinquent.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 500:
            log.warning("sc_dor_delinquent.empty_page", length=len(html or ""))
            return out

        # Parse table rows from the grid
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            # Clean HTML from cells
            clean_cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            # Skip header rows
            if any("name" in c.lower() or "taxpayer" in c.lower() for c in clean_cells[:1]):
                continue

            taxpayer = clean_cells[0] if clean_cells else None
            if not taxpayer or len(taxpayer) < 2:
                continue

            # Find amount and date in any cell
            amount = None
            date_str = None
            for cell in clean_cells:
                if not amount:
                    m = _AMT_RE.search(cell)
                    if m:
                        try:
                            amount = float(m.group().replace("$", "").replace(",", ""))
                        except ValueError:
                            pass
                if not date_str:
                    m = _DATE_RE.search(cell)
                    if m:
                        date_str = m.group()

            # Build a composite description from remaining cells
            desc_parts = [c for c in clean_cells[1:] if c and c != taxpayer]
            description = " | ".join(desc_parts)[:300] if desc_parts else None

            out.append(Listing(
                source="counties_sc.sc_dor_delinquent_taxpayers",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_LIEN,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Statewide",
                defendant=taxpayer,
                judgment_amount=amount,
                description=description,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"sc_dor_delinquent": {
                    "taxpayer": taxpayer,
                    "amount": amount,
                    "date": date_str,
                    "all_cells": clean_cells[:10],
                }},
            ))

        log.info("sc_dor_delinquent.done", count=len(out))
        return out
