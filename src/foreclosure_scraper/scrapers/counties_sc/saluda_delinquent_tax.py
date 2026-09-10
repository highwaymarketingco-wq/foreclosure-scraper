"""Saluda County SC - Delinquent Tax Sale properties.

Saluda County publishes delinquent tax sale properties on its county
website. Annual tax sale lists with owner names, TMS numbers, addresses.

The list lives on the Tax Collector's *Delinquent Tax Sale* SUB-page, not on
the department landing page: the landing page has never contained a <table>
at all (0 <tr> elements), so the original single-URL version of this scraper
could only ever return 0 rows. Both pages are walked now, sale page first.

Publication window (stated on the county page, checked 2026-09-10): the
property list is advertised in the Twin City News and posted to the webpage
for the three weeks before the sale, with a final updated list posted the
Monday before. For the 2026 sale (Tue Dec 8, 2026) that is Nov 19 / Nov 26 /
Dec 3. Outside that window the page carries only the schedule of events, so
a clean 0 in, say, September is the source being correct, not broken.

Free, public, no login.
Slug: counties_sc.saluda_delinquent_tax
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

# The advertised property list is posted on the Delinquent Tax Sale sub-page.
# The department landing page is kept as a secondary target only because the
# office has moved the list between the two in past years; it costs one GET.
SALE_URL = "https://saludacounty.sc.gov/departments/tax-collector/delinquent-tax-sale"
PAGE_URL = "https://saludacounty.sc.gov/departments/tax-collector"
PAGE_URLS = (SALE_URL, PAGE_URL)

# The sale page also publishes a "Schedule of Events" calendar table
# (DATE | EVENTS -> "November 19, 2026" | "1st Advertisement ..."). Those rows
# carry digits and 2 cells, so the generic table walk below would emit ~11 fake
# "listings" every single run. Skip any table that is that calendar.
_EVENT_TABLE_RE = re.compile(r"<t[dh][^>]*>\s*(?:<[^>]+>\s*)*events?\b", re.I)


class SaludaDelinquentTax(BaseScraper):
    slug = "counties_sc.saluda_delinquent_tax"
    name = "Saluda County SC Delinquent Tax Sale"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True
    active_months = (10, 11, 12, 1)

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen: set[tuple] = set()

        for url in PAGE_URLS:
            try:
                html = await get_text(url, impersonate=True, timeout=40.0)
            except Exception as exc:
                log.warning("saluda_tax.fetch_fail", url=url, error=str(exc)[:160])
                continue

            if not html or len(html) < 200:
                continue

            tables = re.findall(r"<table[^>]*>(.*?)</table>", html, re.I | re.S)
            # No <table> wrapper found -> fall back to walking the whole page so
            # a markup change that drops <table> does not silently zero us.
            if not tables:
                tables = [html]

            for table in tables:
                if _EVENT_TABLE_RE.search(table):
                    log.debug("saluda_tax.skip_schedule_table", url=url)
                    continue

                rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.I | re.S)
                for row in rows:
                    cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
                    if len(cells) < 2:
                        continue
                    clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
                    if any(h in c.lower() for c in clean[:2]
                           for h in ("owner", "name", "tms", "map", "#")):
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

                    key = (parcel, addr, owner)
                    if key in seen:
                        continue
                    seen.add(key)

                    out.append(Listing(
                        source="counties_sc.saluda_delinquent_tax",
                        source_url=url,
                        listing_type=ListingType.TAX_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        state="SC",
                        county="Saluda",
                        parcel_id=parcel,
                        defendant=owner,
                        street_address=addr,
                        description=" | ".join(clean[:6]),
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"saluda_delinquent_tax": {"cells": clean[:10]}},
                    ))

        log.info("saluda_tax.done", count=len(out))
        return out
