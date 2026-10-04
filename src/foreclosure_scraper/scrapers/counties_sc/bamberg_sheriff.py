"""Bamberg County SC - Sheriff Sale properties.

Bamberg County Sheriff's Office posts real estate auction listings
for properties being sold via court-ordered sheriff sales.

AUDITED 2026-10-03 (HERMES sec 8 per-source audit, batch 7): live-fetched
the current page -- it is the county's bare department-info page (staff
directory: "Candace Wroten, Administrative Assistant"; "Katelyn Kinard,
Civil Division"; a complaint/commendation form; a FOIA-request blurb). Zero
`<tr>` on the whole page, zero mention of "sale" anywhere in the body text,
and the only linked PDFs are a hazard-mitigation plan and the complaint
form -- no sheriff-sale property roster exists online for this county at
all, not a parsing failure against real content. Same pattern independently
re-confirmed the same day on the sibling `anderson_sheriff` (old .com domain
dead; the real current .org replacement site has no sales page in its own
sitemap either) and `barnwell_sheriff` (its live page is a civil-process FEE
schedule, no property listings) -- small SC counties appear not to publish a
structured online sheriff-sale list at all. Bamberg's real foreclosure-sale
NOTICES (the SC-law-required newspaper advertisement) are already swept
statewide by `newspapers.column_legal_notices`, which explicitly covers the
"Orangeburg, Bamberg and Calhoun" legal-notice region -- so nothing is lost
by this page itself carrying nothing. Left un-disabled (same as
`anderson_sheriff`/`barnwell_sheriff`): the page could legitimately start
publishing a table in the future, and `expected_min_count=0` already makes
a quiet run a non-failure.

Free, public, no login.
Slug: counties_sc.bamberg_sheriff
Category: sheriff_sale
ListingType: SHERIFF_SALE
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

PAGE_URL = "https://www.bambergcounty.sc.gov/public-safety/sheriffs-office"


class BambergSheriff(BaseScraper):
    slug = "counties_sc.bamberg_sheriff"
    name = "Bamberg County SC Sheriff Sales"
    category = "sheriff_sale"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("bamberg_sheriff.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if any(h in c.lower() for c in clean[:2] for h in ("case", "defendant", "plaintiff", "#")):
                continue
            if not any(re.search(r"\d", c) for c in clean):
                continue

            case_no = None
            for c in clean:
                m = re.search(r"\b(\d{2,4}[-\s]?(?:CP|CV|CA|GS|CR|L)[-\s]?\d+)\b", c, re.I)
                if m:
                    case_no = m.group(1)
                    break

            addr = None
            for c in clean:
                if re.search(r"\d+\s+\w+", c):
                    addr = c
                    break

            out.append(Listing(
                source="counties_sc.bamberg_sheriff",
                source_url=PAGE_URL,
                listing_type=ListingType.SHERIFF_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Bamberg",
                case_number=case_no,
                street_address=addr,
                defendant=clean[0] if clean else None,
                description=" | ".join(clean[:6]),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"bamberg_sheriff": {"cells": clean[:10]}},
            ))

        log.info("bamberg_sheriff.done", count=len(out))
        return out
