"""Lancaster County SC — Delinquent Tax properties.

Lancaster County posts its delinquent tax sale notice, procedures and (closer to
the sale) the advertised property list on the Delinquent Tax Collection pages at
lancastercountysc.gov.

URL note (2026-09-10): the old hardcoded target was an AlertCenter alert
(``AlertCenter.aspx?AID=A-Friendly-Reminder-The-Delinquent-Tax-C-16``) and now
returns HTTP 404 — CivicPlus alert IDs rotate every time the county re-posts the
reminder, so an alert URL can never be a durable source. The same notice text
now lives on the permanent department pages below, which are what the county's
own procedures page points at: "A list of all delinquent properties will be
advertised in the local newspaper (The Lancaster News) and on the county website
under the Delinquent Tax Department."

Cadence: the 2026 sale is Monday November 9, 2026; the county states the updated
property list posts by November 6, 2026 after 5 pm. So between the March 16
delinquency date and roughly mid-October these pages carry the notice only and
this source is legitimately listless.

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
from ._sc_tax_table import is_usable_row

log = structlog.get_logger()

BASE = "https://www.lancastercountysc.gov"
# Permanent department pages (verified live 2026-09-10, HTTP 200). The first is
# the canonical replacement for the dead AlertCenter alert.
PAGE_URLS = (
    f"{BASE}/194/Delinquent-Tax-Collection",
    f"{BASE}/198/Tax-Sale-Procedures",
)
PAGE_URL = PAGE_URLS[0]  # back-compat for anything referencing the old name

# The advertised list arrives as a document link, not a table. CivicPlus serves
# it from /DocumentCenter/View/<id>/..., which need not carry "delinquent" in the
# path — so match on the href OR the anchor text, and skip the standing
# procedure/registration/bidder paperwork that is not a property list.
_DOC_LINK_RE = re.compile(
    r'<a[^>]+href="([^"]*(?:/DocumentCenter/View/[^"]*|\.pdf[^"]*))"[^>]*>(.*?)</a>',
    re.I | re.S,
)
_LIST_HINT_RE = re.compile(r"delinquent|tax\s*sale", re.I)
_NOT_A_LIST_RE = re.compile(
    r"procedure|application|bidder|registration|register|form|faq|instruction|"
    r"agenda|minutes|receipt|affidavit",
    re.I,
)


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
        doc_links: list[tuple[str, str]] = []

        for page_url in PAGE_URLS:
            try:
                html = await get_text(page_url, impersonate=True, timeout=40.0)
            except Exception as exc:
                log.warning("lancaster_tax.fetch_fail", url=page_url,
                            error=str(exc)[:160])
                continue

            if not html or len(html) < 200:
                continue

            # Candidate property-list documents (published ~Oct/Nov each year).
            for href, anchor in _DOC_LINK_RE.findall(html):
                text = re.sub(r"<[^>]+>", " ", anchor)
                text = re.sub(r"\s+", " ", text).strip()
                blob = f"{href} {text}"
                if not _LIST_HINT_RE.search(blob) or _NOT_A_LIST_RE.search(blob):
                    continue
                url = href if href.startswith("http") else f"{BASE}{href}"
                if url not in {u for u, _ in doc_links}:
                    doc_links.append((url, text))

            # Property rows, when the county renders the list as a table.
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
            for row in rows:
                cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
                if len(cells) < 2:
                    continue
                clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
                if any(h in c.lower() for c in clean[:2]
                       for h in ("owner", "name", "tms", "map", "#", "header")):
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
                    source="counties_sc.lancaster_delinquent_tax",
                    source_url=page_url,
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

        # If we found list documents but no parsed rows, record them for follow-up
        # (the doc-OCR lane can read the PDF once the county posts it).
        if doc_links and not out:
            for url, text in doc_links[:5]:
                out.append(Listing(
                    source="counties_sc.lancaster_delinquent_tax",
                    source_url=url,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="Lancaster",
                    description=f"Delinquent tax list document: {text or url}",
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"lancaster_delinquent_tax": {
                        "pdf_url": url, "link_text": text, "is_pdf_link": True}},
                ))

        log.info("lancaster_tax.done", count=len(out), docs=len(doc_links))
        return out
