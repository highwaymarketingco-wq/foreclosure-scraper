"""EPA Superfund NPL sites — environmental contamination distress signal.

The EPA publishes the National Priorities List (NPL) of Superfund sites.
Data is available via the EPA's EnviroFacts REST API and the SEPLAN dataset.

  https://ejscreen.epa.gov/mapper (interactive map)
  https://enviro.epa.gov (EnviroFacts API)

We query the SEPLAN Superfund NPL dataset via the EnviroFacts API for NC and SC
sites. Each site includes: site name, address, city, county, state, ZIP, lat/lng,
EPA ID, NPL status, and contamination type.

This is an enrichment/distress signal — properties near Superfund sites have
elevated distress risk (environmental stigma, value impact, potential buyout).

Free, public, no key needed for basic queries.
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
