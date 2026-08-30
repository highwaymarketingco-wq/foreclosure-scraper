"""FEMA Disaster Declarations — federal disaster declaration list.

FEMA publishes a public list of all declared disasters at
fema.gov/disaster/declarations.  Each entry has a disaster title (e.g.
"Hurricane Helene"), declaration type (Major Disaster, Emergency, Fire
Management), incident period, and declaration date.

This is a distress signal for property intelligence: properties in
federally-declared disaster zones may have damage, insurance disputes,
or FEMA buyout potential — all motivated-seller indicators.

The page returns 403 on plain httpx, so we use impersonate=True (stealth
browser headers).  Data is in .views-listing rows.

Free, public, no login.
Slug: national.fema_disasters
Category: national_aggregator
ListingType: DISTRESSED
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

PAGE_URL = "https://www.fema.gov/disaster/declarations"


class FEMADisasters(BaseScraper):
    slug = "national.fema_disasters"
    name = "FEMA Disaster Declarations"
    category = "national_aggregator"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=40.0)
        except Exception as exc:
            log.warning("fema_disasters.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 500:
            log.warning("fema_disasters.empty_page", length=len(html or ""))
            return out

        # FEMA uses Drupal views-listing — each disaster is in a .views-row
        rows = re.findall(r'<div[^>]*class="[^"]*views-row[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="[^"]*views-row|</div>\s*</div)', html, re.I | re.S)

        # Fallback: try li elements with disaster links
        if not rows:
            rows = re.findall(r'<li[^>]*>(.*?)</li>', html, re.I | re.S)

        for row in rows:
            # Extract disaster title from link text
            link_match = re.search(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', row, re.I | re.S)
            if not link_match:
                continue
            url = link_match.group(1).strip()
            title = re.sub(r"<[^>]+>", "", link_match.group(2)).strip()
            if not title or len(title) < 5:
                continue

            # Extract disaster number from title (e.g., "EM-3651-IN" or "DR-4733-NC")
            fema_id_match = re.search(r"((?:EM|DR|FM)-\d+-[A-Z]{2})", title)
            fema_id = fema_id_match.group(1) if fema_id_match else None

            # Extract states from title (last part of FEMA ID or state abbreviations)
            state_match = re.search(r"-([A-Z]{2})\s*$", title)
            state = state_match.group(1) if state_match else None

            # Extract date if present
            date_match = re.search(r"(\w+\s+\d{1,2},?\s+\d{4})", row)
            date_str = date_match.group(1) if date_match else None

            # Clean description
            desc_text = re.sub(r"<[^>]+>", " ", row)
            desc_text = re.sub(r"\s+", " ", desc_text).strip()[:300]

            from urllib.parse import urljoin
            full_url = urljoin(PAGE_URL, url) if url and not url.startswith("http") else url

            out.append(Listing(
                source="national.fema_disasters",
                source_url=full_url or PAGE_URL,
                listing_type=ListingType.DISTRESSED,
                property_kind=PropertyKind.UNKNOWN,
                state=state,
                county="Statewide",
                description=f"{title}. {date_str or ''}".strip(),
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={"fema_disaster": {
                    "title": title,
                    "fema_id": fema_id,
                    "date": date_str,
                    "url": full_url,
                    "description": desc_text,
                }},
            ))

        log.info("fema_disasters.done", count=len(out))
        return out
