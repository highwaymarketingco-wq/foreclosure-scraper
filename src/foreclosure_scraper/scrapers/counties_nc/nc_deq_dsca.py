"""NC DEQ DSCA — Dry-Cleaning Solvent Cleanup Act site list.

The NC Department of Environmental Quality (DEQ) maintains a list of
properties contaminated by dry-cleaning solvents under the DSCA program.
These properties have environmental contamination that can affect
property value and marketability — a distress signal for property
intelligence.

Data source: deq.nc.gov DSCA site list.  Properties are listed in a
table with site name, address, and contamination status.

Free, public, no login.
Slug: counties_nc.nc_deq_dsca
Category: environmental
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

PAGE_URL = "https://www.deq.nc.gov/about/divisions/waste-management/dry-cleaning-solvent-cleanup-act-program"


class NCDEQDSCA(BaseScraper):
    slug = "counties_nc.nc_deq_dsca"
    name = "NC DEQ DSCA Contamination Sites"
    category = "environmental"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("nc_deq_dsca.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if any(h in c.lower() for c in clean[:2] for h in ("site", "name", "address", "city", "county", "status", "#")):
                continue

            site_name = clean[0] if clean else None
            addr = None
            city = None
            county = None
            for c in clean[1:]:
                if re.search(r"\d+\s+\w+", c) and not addr:
                    addr = c
                if ", NC" in c and not city:
                    city = c.split(",")[0].strip()
                if "county" in c.lower() and not county:
                    county = re.sub(r"(?i)\s*county\s*", "", c).strip()

            out.append(Listing(
                source="counties_nc.nc_deq_dsca",
                source_url=PAGE_URL,
                listing_type=ListingType.DISTRESSED,
                property_kind=PropertyKind.UNKNOWN,
                state="NC",
                county=county,
                city=city,
                street_address=addr,
                description=f"DSCA contamination site: {site_name}",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"nc_deq_dsca": {"site_name": site_name, "cells": clean[:10]}},
            ))

        # Fallback: list items
        if not out:
            items = re.findall(r"<li[^>]*>(.*?)</li>", html, re.I | re.S)
            for item in items:
                text = re.sub(r"<[^>]+>", "", item).strip()
                if len(text) < 15:
                    continue
                addr_match = re.search(r"\d+\s+\w+[\w\s,]+(?:NC|N\.C\.)", text, re.I)
                if not addr_match:
                    continue
                out.append(Listing(
                    source="counties_nc.nc_deq_dsca",
                    source_url=PAGE_URL,
                    listing_type=ListingType.DISTRESSED,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    street_address=addr_match.group().strip(),
                    description=text[:300],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"nc_deq_dsca": {"text": text[:200]}},
                ))

        log.info("nc_deq_dsca.done", count=len(out))
        return out
