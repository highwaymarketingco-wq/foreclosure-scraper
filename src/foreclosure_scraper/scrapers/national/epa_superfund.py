"""EPA Superfund NPL sites — environmental contamination distress signal.

DISABLED 2026-09-15 (national.* zero-row audit) — confirmed dead AND
redundant. The `data.epa.gov/ef/seplan/SEPLAN/...` endpoint this module
targets returns 403 `MissingAuthenticationTokenException` (an AWS API
Gateway "no such route" error, not a real auth requirement — the route
itself no longer exists). Went looking for the correct modern table name
under `data.epa.gov/efservice/...` and found something better: this
project ALREADY has a working Superfund source.
`counties_generic.epa_frs_sites.py` covers the exact same signal — its
own docstring documents that the direct SEMS/SEPLAN endpoint 500'd back
on 2026-08-06 (the same failure family this module is hitting today) and
was fixed by reading Superfund/CERCLIS data through the Facility Registry
Service instead (`frs.frs_program_facility`, `pgm_sys_acrnm=SEMS`), which
DOES answer 200. That source is live and landed 269 rows earlier this
same audit (`counties_generic.epa_frs.sems` + `.acres`). This module never
contributed anything the FRS-based one doesn't already cover; disabled as
a confirmed redundant duplicate rather than chasing a working URL for a
signal the board already has.

Original module intent, for reference: the EPA publishes the National
Priorities List (NPL) of Superfund sites — a distress signal for
properties near contamination (environmental stigma, value impact,
potential buyout).

Slug: national.epa_superfund
Category: reo
ListingType: REO
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# EnviroFacts SEPLAN dataset — Superfund NPL sites
API_URL = (
    "https://data.epa.gov/ef/seplan/"
    "SEPLAN/ROWS/0:100/JSON"
)
HEADERS = {"Accept": "application/json"}


class EPASuperfund(BaseScraper):
    slug = "national.epa_superfund"
    name = "EPA Superfund NPL Sites"
    category = "reo"
    timeout_s = 90.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        # Disabled — see module docstring. Confirmed dead endpoint AND
        # redundant with counties_generic.epa_frs_sites.py (already live,
        # covers the same SEMS/Superfund signal via a working path).
        return []

    async def _disabled_fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            # Query NC and SC Superfund sites via EnviroFacts
            for state in ("NC", "SC"):
                url = f"https://data.epa.gov/ef/seplan/SEPLAN/ROWS/0:200/JSON?search={state}"
                text = await get_text(url, timeout=30.0)
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except Exception:
                    continue

                rows = data if isinstance(data, list) else data.get("rows", data.get("results", []))
                for row in rows:
                    # Fields vary by API version — try common keys
                    name = row.get("SITE_NAME") or row.get("SITENAME") or row.get("siteName")
                    addr = row.get("SITE_ADDR") or row.get("ADDRESS") or row.get("siteAddress")
                    city = row.get("CITY_NAME") or row.get("CITY") or row.get("cityName")
                    county = row.get("COUNTY_NAME") or row.get("COUNTY") or row.get("countyName")
                    epa_id = row.get("EPA_ID") or row.get("SEMS_ID") or row.get("epaID")
                    lat = row.get("LATITUDE") or row.get("LAT") or row.get("latitude")
                    lng = row.get("LONGITUDE") or row.get("LON") or row.get("LNG") or row.get("longitude")
                    npl_status = row.get("NPL_STATUS") or row.get("nplStatus")

                    if lat:
                        try:
                            lat = float(lat)
                        except (TypeError, ValueError):
                            lat = None
                    if lng:
                        try:
                            lng = float(lng)
                        except (TypeError, ValueError):
                            lng = None

                    raw = {
                        "epa_id": epa_id,
                        "site_name": name,
                        "npl_status": npl_status,
                        "contamination_type": "superfund_npl",
                        "source_url": "https://www.epa.gov/superfund/search-superfund-sites",
                    }

                    out.append(
                        Listing(
                            source=self.slug,
                            source_url="https://www.epa.gov/superfund/search-superfund-sites",
                            listing_type=ListingType.REO,
                            street_address=addr,
                            city=city,
                            county=county,
                            state=state,
                            latitude=lat,
                            longitude=lng,
                            property_kind=PropertyKind.LAND,
                            raw=raw,
                        )
                    )

        except Exception as exc:
            log.warning("epa_superfund.fetch_fail", error=str(exc)[:160])

        log.info("epa_superfund.fetch_done", count=len(out))
        return out
