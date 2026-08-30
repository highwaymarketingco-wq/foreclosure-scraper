"""Anderson County SC - Sheriff Sale properties.

Anderson County Sheriff's Office posts real estate auction listings
for properties being sold via court-ordered sheriff sales. Properties
come from mortgage foreclosures and judgment executions.

Free, public, no login.
Slug: counties_sc.anderson_sheriff
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

PAGE_URL = "https://www.andersonsheriff.com/sheriff-sales"


class AndersonSheriff(BaseScraper):
    slug = "counties_sc.anderson_sheriff"
    name = "Anderson County SC Sheriff Sales"
    category = "sheriff_sale"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("anderson_sheriff.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        # Find sale entries - sheriff sale pages typically use tables or divs
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

            # Extract case number
            case_no = None
            for c in clean:
                m = re.search(r"\b(\d{2,4}[-\s]?(?:CP|CV|CA|GS|CR|L)[-\s]?\d+)\b", c, re.I)
                if m:
                    case_no = m.group(1)
                    break

            # Extract address
            addr = None
            for c in clean:
                if re.search(r"\d+\s+\w+", c):
                    addr = c
                    break

            out.append(Listing(
                source="counties_sc.anderson_sheriff",
                source_url=PAGE_URL,
                listing_type=ListingType.SHERIFF_SALE,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county="Anderson",
                case_number=case_no,
                street_address=addr,
                defendant=clean[0] if clean else None,
                description=" | ".join(clean[:6]),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"anderson_sheriff": {"cells": clean[:10]}},
            ))

        log.info("anderson_sheriff.done", count=len(out))
        return out
