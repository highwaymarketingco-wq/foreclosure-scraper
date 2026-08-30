"""Asheville NC — Minimum Housing / Unsafe Building condemnations.

The City of Asheville publishes minimum housing violation cases and
condemned/unsafe building notices.  These are properties flagged by
the city for housing code violations — a strong pre-foreclosure distress
signal (owners face fines, repair orders, or condemnation).

Data source: Asheville's open data portal and code enforcement pages
at ashevillenc.gov.  The page lists properties with case numbers,
addresses, and violation types.

Free, public, no login.
Slug: city_websites.asheville_min_housing
Category: code_enforcement
ListingType: DISTRESSED
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

PAGE_URL = "https://www.ashevillenc.gov/department/development-services/minimum-housing/"


class AshevilleMinHousing(BaseScraper):
    slug = "city_websites.asheville_min_housing"
    name = "Asheville NC Minimum Housing / Unsafe Buildings"
    category = "code_enforcement"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("asheville_min_housing.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        # Look for property listing tables
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if any(h in c.lower() for c in clean[:2] for h in ("address", "case", "violation", "status", "#", "owner")):
                continue

            addr = clean[0] if clean else None
            case_num = None
            for c in clean:
                m = re.search(r"\b(\d{2,}[A-Z]{2,}\d+)\b", c) or re.search(r"\b(RES-?\d+)\b", c, re.I)
                if m:
                    case_num = m.group(1)
                    break

            violation_type = None
            for c in clean[1:]:
                if any(kw in c.lower() for kw in ("dilapidated", "unsafe", "condemn", "vacant", "boarded", "nuisance")):
                    violation_type = c
                    break

            out.append(Listing(
                source="city_websites.asheville_min_housing",
                source_url=PAGE_URL,
                listing_type=ListingType.DISTRESSED,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county="Buncombe",
                city="Asheville",
                street_address=addr,
                case_number=case_num,
                description=violation_type or " | ".join(clean[:6]) if clean else None,
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"asheville_min_housing": {"cells": clean[:10], "violation_type": violation_type}},
            ))

        # Fallback: look for property cards or list items
        if not out:
            items = re.findall(r'<div[^>]*class="[^"]*(?:property|case|listing|violation)[^"]*"[^>]*>(.*?)</div>', html, re.I | re.S)
            if not items:
                items = re.findall(r"<li[^>]*>(.*?)</li>", html, re.I | re.S)
            for item in items:
                text = re.sub(r"<[^>]+>", " ", item)
                text = re.sub(r"\s+", " ", text).strip()
                if len(text) < 15:
                    continue
                addr_match = re.search(r"\d+\s+\w+[\w\s]+(?:st|ave|rd|dr|ln|ct|blvd|hwy|way|pl|cir|trl)", text, re.I)
                if not addr_match:
                    continue
                out.append(Listing(
                    source="city_websites.asheville_min_housing",
                    source_url=PAGE_URL,
                    listing_type=ListingType.DISTRESSED,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Buncombe",
                    city="Asheville",
                    street_address=addr_match.group().strip(),
                    description=text[:300],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"asheville_min_housing": {"text": text[:200]}},
                ))

        log.info("asheville_min_housing.done", count=len(out))
        return out
