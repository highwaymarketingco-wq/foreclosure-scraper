"""Union County SC - Delinquent Tax Sale properties.

Union County publishes delinquent tax sale properties on its county
website. Annual tax sale lists with owner names, TMS numbers, addresses.

Free, public, no login.
Slug: counties_sc.union_delinquent_tax
Category: county_tax
ListingType: TAX_SALE

2026-09-28 re-verification (MASTER_GAPS had this flagged "DNS failure"):
PAGE_URL (gearupunionsc.com, the county's current WordPress site) resolves
and returns HTTP 200 fine -- the DNS-failure entry is stale. But like
Laurens, this page (and its sibling
gearupunionsc.com/departments/delinquent-tax-office/) carries NO HTML
table (0 <table> tags on either) -- both just link out to
uniontreasurer.qpaybill.com/Taxes/TaxesDefaultType4.aspx. So the 0-row
result below is a correct read of an empty page.

Separately probed the county's OLD pre-migration domain
(countyofunion.org, the classic-ASP "cpage.asp" site turned up by search --
this is likely what MASTER_GAPS's "DNS failure" / IIS-8.5 note was tracking
before this re-check): it now resolves and 301-redirects cleanly (both
HTTP and HTTPS, no connection resets in this test) straight to
gearupunionsc.com/, with the old cpage.asp deep links 404ing on the far
side. So that legacy host has been fully retired into the WordPress site
above, not merely broken -- no separate free path was found or is needed
there. A short probe of a few other plausible legacy hostnames
(co.union.sc.us, unioncountysc.gov, unioncounty.sc.gov, sc-union.us, and
www variants) found none resolving.

None of this matters for real coverage, though: Union's actual per-parcel
delinquent-tax roll -- owner, address, TMS, amount owed, tax year -- is
already live via `counties_sc.qpaybill_delinquent_roll`
(COUNTIES["Union"] = "uniontreasurer", verified live 2026-09-10).
Re-confirmed live again 2026-09-28 with a single-prefix smoke test ("S")
returning 25 real 2025 rows with dollar amounts (e.g. SAILORS JERRI (LE),
045-00-00-069 000, $5,561.72 unpaid). Do not duplicate that sweep here --
this module is kept only in case the county ever republishes a table.
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

PAGE_URL = "https://gearupunionsc.com/officials/treasurer/"


class UnionDelinquentTax(BaseScraper):
    slug = "counties_sc.union_delinquent_tax"
    name = "Union County SC Delinquent Tax Sale"
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
            log.warning("union_tax.fetch_fail", error=str(exc)[:160])
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
                source="counties_sc.union_delinquent_tax",
                source_url=PAGE_URL,
                listing_type=ListingType.TAX_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Union",
                parcel_id=parcel,
                defendant=owner,
                street_address=addr,
                description=" | ".join(clean[:6]),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"union_delinquent_tax": {"cells": clean[:10]}},
            ))

        log.info("union_tax.done", count=len(out))
        return out
