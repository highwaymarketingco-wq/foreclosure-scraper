"""Schneider qPublic SC assessor cards — Cloudflare-walled property search.

qPublic (qpublic.schneidercorp.com) hosts assessor/property card data for
multiple SC counties behind a Cloudflare "verify you're human" challenge.

The wall_bypass escalation chain (curl-cffi → pydoll → nodriver) handles
Cloudflare automatically. We use http_client.get_text(wall_bypass=True)
for the search, then parse the HTML results table.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://qpublic.schneidercorp.com"

_COUNTY_PAGES = {
    "berkeley": {"app": "BerkeleySC"},
    "beaufort": {"app": "BeaufortSC"},
    "colleton": {"app": "ColletonSC"},
    "darlington": {"app": "DarlingtonSC"},
    "dillon": {"app": "DillonSC"},
    "edgefield": {"app": "EdgefieldSC"},
    "fairfield": {"app": "FairfieldSC"},
    "georgetown": {"app": "GeorgetownSC"},
    "greenwood": {"app": "GreenwoodSC"},
    "hampton": {"app": "HamptonSC"},
    "jasper": {"app": "JasperSC"},
    "kershaw": {"app": "KershawSC"},
    "lancaster": {"app": "LancasterSC"},
    "laurens": {"app": "LaurensSC"},
    "lexington": {"app": "LexingtonSC"},
    "marion": {"app": "MarionSC"},
    "marlboro": {"app": "MarlboroSC"},
    "mccormick": {"app": "McCormickSC"},
    "newberry": {"app": "NewberrySC"},
    "oconee": {"app": "OconeeSC"},
    "orangeburg": {"app": "OrangeburgSC"},
    "pickens": {"app": "PickensSC"},
    "saluda": {"app": "SaludaSC"},
    "sumter": {"app": "SumterSC"},
    "union": {"app": "UnionSC"},
    "williamsburg": {"app": "WilliamsburgSC"},
}


class ScQpublicScraper(BaseScraper):
    """SC qPublic assessor cards via wall_bypass."""

    slug = "counties_sc.sc_qpublic"
    name = "SC qPublic Assessor Cards"
    category = "assessor"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        for county, cfg in _COUNTY_PAGES.items():
            try:
                url = f"{_BASE}/Application.aspx?App={cfg['app']}&Page=search"

                log.info("sc_qpublic.fetching", county=county)
                html = await client.get_text(
                    url,
                    wall_bypass=True,
                    timeout=30.0,
                )

                if not html or len(html) < 500:
                    log.warning("sc_qpublic.empty_response", county=county)
                    continue

                if "challenge" in html.lower() and "cf-" in html.lower():
                    log.warning("sc_qpublic.cloudflare_blocked", county=county)
                    continue

                soup = BeautifulSoup(html, "html.parser")
                rows = soup.select("table.searchResults tr, table.grid tr, .result-item")

                for row in rows[1:]:
                    cells = row.find_all("td")
                    if len(cells) < 3:
                        continue

                    parcel_id = cells[0].get_text(strip=True)
                    owner = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                    addr = cells[2].get_text(strip=True) if len(cells) > 2 else ""

                    if not parcel_id or not addr:
                        continue

                    results.append(Listing(
                        source=self.slug,
                        source_url=url,
                        listing_type=ListingType.UNKNOWN,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=addr,
                        county=county.title(),
                        state="SC",
                        parcel_id=parcel_id,
                        owner_name=owner,
                        raw={"county": county, "source": "qpublic"},
                    ))

                log.info("sc_qpublic.county_done", county=county, found=len(results))

            except Exception as exc:
                log.warning("sc_qpublic.county_error", county=county, error=str(exc)[:200])

        return results
