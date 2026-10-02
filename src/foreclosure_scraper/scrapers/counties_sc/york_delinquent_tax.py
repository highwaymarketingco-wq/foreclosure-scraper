"""York County SC — Tax Collection / Delinquent Tax properties.

York County posts delinquent tax information at
yorkcountysc.gov/216.  The page lists properties with delinquent taxes
heading to the annual tax sale.

Free, public, no login.

AUDITED 2026-10-01: the document-link fallback below used to emit a BARE
placeholder Listing (a link + a label, no owner/parcel/address/amount at
all) for any matched document, never actually fetching or parsing it. Live
right now (no real per-parcel list published; York's season runs Oct-Jan),
the only matching document is "OVERAGE-CLAIM-LIST" -- which is also an exact
duplicate of what counties_sc.york_overage_claims.py already fetches and
parses properly. So this scraper's live output was one noise row that both
told the operator nothing (no fields) and doubled up a different source's
real data. Fixed two ways: (1) overage-claim documents are excluded here --
that's york_overage_claims.py's job -- so only an actual delinquent TAX SALE
list is matched; (2) a matched document is now downloaded and parsed with
pdfplumber for real per-parcel rows (owner/parcel/address/amount), the same
table-extraction approach sc_tax_delinquent.py already uses elsewhere in this
codebase, instead of being recorded as a content-free link. If a matched PDF
yields no table rows, nothing is emitted (no fabricated placeholder) and the
PDF-fail is logged for visibility instead.

Slug: counties_sc.york_delinquent_tax
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client, get_text
from ...models import Listing, ListingType, PropertyKind
from ._sc_tax_table import is_usable_row

log = structlog.get_logger()

PAGE_URL = "https://www.yorkcountysc.gov/216/Tax-Collection"


class YorkDelinquentTax(BaseScraper):
    slug = "counties_sc.york_delinquent_tax"
    name = "York County SC Delinquent Tax Collection"
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
            log.warning("york_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        # York County uses CivicPlus CMS — look for property listings in tables
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
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

            # Shared junk-row gate: header/office-hours rows and rows with no TMS
            # never become leads. See _sc_tax_table for why this is here and not
            # left to _active_only() in main.py.
            if not is_usable_row(clean, parcel):
                continue
            out.append(Listing(
                source="counties_sc.york_delinquent_tax",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="York",
                parcel_id=parcel,
                defendant=owner,
                street_address=addr,
                description=" | ".join(clean[:6]) if clean else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"york_delinquent_tax": {"cells": clean[:10]}},
            ))

        # Look for document links to an actual delinquent TAX SALE list. York
        # publishes every document through the CivicPlus DocumentCenter, whose
        # URLs carry NO ".pdf" extension (/DocumentCenter/View/<id>/<Slug>).
        # AUDITED 2026-10-01: "overage" is excluded here -- that is
        # counties_sc.york_overage_claims.py's own document, parsed properly
        # there; matching it here only produced a content-free duplicate.
        if not out:
            candidates = re.findall(
                r'href="(/DocumentCenter/View/\d+/[^"?#]+|[^"]*\.pdf[^"]*)"',
                html, re.I)
            seen: set[str] = set()
            for doc_url in candidates:
                label = re.sub(r"[-_]+", " ", doc_url.rsplit("/", 1)[-1]).strip()
                if "overage" in label.lower():
                    continue  # york_overage_claims.py's document, not this one's
                # Keep actual rosters ("2026 Delinquent Tax Sale List") and
                # skip the standing procedure sheets, installment guidelines
                # and bidder forms on the same page.
                if not re.search(r"\blist\b", label, re.I):
                    continue
                if not re.search(r"delinquent|tax|sale", label, re.I):
                    continue
                if doc_url in seen:
                    continue
                seen.add(doc_url)
                full_url = doc_url if doc_url.startswith("http") else f"https://www.yorkcountysc.gov{doc_url}"
                out.extend(await self._parse_list_pdf(full_url, label))
                if len(out) >= 2000:
                    break

        log.info("york_tax.done", count=len(out))
        return out

    async def _parse_list_pdf(self, url: str, label: str) -> list[Listing]:
        """Download and table-parse a matched delinquent tax-sale list PDF.
        Returns [] (never a content-free placeholder) if it can't be read as a
        real table -- same posture as counties_sc.sc_tax_delinquent.py's PDF
        reader."""
        try:
            async with client(timeout=60.0) as c:
                resp = await c.get(url, follow_redirects=True, timeout=60.0)
            if resp.status_code != 200:
                log.warning("york_tax.pdf_http_fail", url=url, status=resp.status_code)
                return []
            import pdfplumber
        except Exception as exc:  # noqa: BLE001
            log.warning("york_tax.pdf_fetch_fail", url=url, error=str(exc)[:160])
            return []

        out: list[Listing] = []
        now = datetime.utcnow()
        try:
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                for page in pdf.pages:
                    for tbl in page.extract_tables() or []:
                        if not tbl or len(tbl) < 2:
                            continue
                        header = [str(c or "").lower() for c in tbl[0]]
                        if not any("owner" in h or "name" in h or "tms" in h
                                   or "map" in h or "parcel" in h for h in header):
                            continue
                        addr_col = next((i for i, h in enumerate(header) if "addr" in h or "descript" in h), None)
                        owner_col = next((i for i, h in enumerate(header)
                                          if "owner" in h or "name" in h or "taxpayer" in h), None)
                        parcel_col = next((i for i, h in enumerate(header)
                                           if "parcel" in h or "tms" in h or "map" in h), None)
                        amt_col = next((i for i, h in enumerate(header) if "amount" in h or "due" in h), None)
                        for row in tbl[1:]:
                            if not row or all(not c for c in row):
                                continue
                            owner = str(row[owner_col] or "").strip() if owner_col is not None else ""
                            parcel = str(row[parcel_col] or "").strip() if parcel_col is not None else ""
                            addr = str(row[addr_col] or "").strip() if addr_col is not None else ""
                            amt_text = str(row[amt_col] or "").strip() if amt_col is not None else ""
                            if not owner and not parcel:
                                continue
                            amount = None
                            am = re.search(r"\$?\s*([\d,]+\.?\d*)", amt_text)
                            if am:
                                try:
                                    amount = float(am.group(1).replace(",", ""))
                                except ValueError:
                                    pass
                            out.append(Listing(
                                source=self.slug,
                                source_url=url,
                                listing_type=ListingType.TAX_SALE,
                                property_kind=PropertyKind.UNKNOWN,
                                state="SC",
                                county="York",
                                parcel_id=parcel or None,
                                defendant=owner or None,
                                street_address=addr or None,
                                opening_bid=amount,
                                description=f"York delinquent tax sale list ({label}): {owner or '?'}",
                                first_seen=now, last_seen=now,
                                raw={"york_delinquent_tax": {"source_pdf": url, "amount_due": amount}},
                            ))
        except Exception as exc:  # noqa: BLE001
            log.warning("york_tax.pdf_parse_fail", url=url, error=str(exc)[:160])
            return []
        if not out:
            log.warning("york_tax.pdf_no_table_rows", url=url)
        return out
