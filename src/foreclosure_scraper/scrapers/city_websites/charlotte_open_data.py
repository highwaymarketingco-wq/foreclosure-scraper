"""Charlotte Open Data Portal — Socrata API for code violations, crime, and permits.

Charlotte's open data portal at data.charlottenc.gov provides free datasets
via the Socrata API (no key required for public datasets):

  - Code Violations: https://data.charlottenc.gov/resource/c6er-5c2c.json
  - Crime Incidents: https://data.charlottenc.gov/resource/6jx5-894j.json
  - Building Permits: https://data.charlottenc.gov/resource/4qfb-edib.json

Each dataset returns JSON with address, date, description, and location data.
We query code violations and building permits to find distressed properties
— properties with open code violations or demolition permits are motivated sellers.

Free, public, no API key required (Socrata public datasets).
Slug: city_websites.charlotte_open_data
Category: city
ListingType: DISTRESSED
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

CODE_VIOLATIONS_URL = "https://data.charlottenc.gov/resource/c6er-5c2c.json"
BUILDING_PERMITS_URL = "https://data.charlottenc.gov/resource/4qfb-edib.json"

# Limit to recent records for code violations — only open/recent violations matter
QUERY_PARAMS = "?$limit=500&$order=date1%20DESC&$where=date1%20%3E%20%272024-01-01%27"


class CharlotteOpenData(BaseScraper):
    slug = "city_websites.charlotte_open_data"
    name = "Charlotte Open Data Portal"
    category = "city"
    timeout_s = 60.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_addrs: set[str] = set()

        # 1. Code violations — properties with open violations are distressed
        try:
            url = f"{CODE_VIOLATIONS_URL}{QUERY_PARAMS}"
            text = await get_text(url, timeout=30.0)
            if text:
                records = json.loads(text)
                for rec in records:
                    addr = rec.get("address") or rec.get("geo_street") or rec.get("location_address")
                    if not addr:
                        continue
                    addr = addr.strip()
                    if addr in seen_addrs:
                        continue
                    seen_addrs.add(addr)

                    raw = {
                        "violation_type": rec.get("violation_type") or rec.get("type"),
                        "status": rec.get("status"),
                        "date": rec.get("date1") or rec.get("dateopendata"),
                        "source_url": CODE_VIOLATIONS_URL,
                    }

                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=CODE_VIOLATIONS_URL,
                            listing_type=ListingType.DISTRESSED,
                            street_address=addr,
                            city="Charlotte",
                            state="NC",
                            county="Mecklenburg",
                            property_kind=PropertyKind.UNKNOWN,
                            raw=raw,
                        )
                    )
        except Exception as exc:
            log.warning("charlotte.code_violations_fail", error=str(exc)[:160])

        # 2. Building permits — demolition permits signal distress
        try:
            url = f"{BUILDING_PERMITS_URL}?$limit=200&$order=permitissueddate%20DESC&$where=permittype%20=%20%27Demolition%27"
            text = await get_text(url, timeout=30.0)
            if text:
                records = json.loads(text)
                for rec in records:
                    addr = rec.get("address") or rec.get("permithouse") or rec.get("location")
                    if not addr:
                        continue
                    addr = addr.strip()
                    if addr in seen_addrs:
                        continue
                    seen_addrs.add(addr)

                    raw = {
                        "permit_type": rec.get("permittype"),
                        "permit_status": rec.get("permitstatus"),
                        "issued_date": rec.get("permitissueddate"),
                        "source_url": BUILDING_PERMITS_URL,
                    }

                    out.append(
                        Listing(
                            source=self.slug,
                            source_url=BUILDING_PERMITS_URL,
                            listing_type=ListingType.DISTRESSED,
                            street_address=addr,
                            city="Charlotte",
                            state="NC",
                            county="Mecklenburg",
                            property_kind=PropertyKind.UNKNOWN,
                            raw=raw,
                        )
                    )
        except Exception as exc:
            log.warning("charlotte.building_permits_fail", error=str(exc)[:160])

        log.info("charlotte.fetch_done", count=len(out))
        return out
