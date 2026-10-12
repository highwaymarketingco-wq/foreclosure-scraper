"""Datacenter IP-blocked NC tax sites — Rutherford County, Lee County.

rutherfordcountync.gov and similar refuse connections from datacenter IPs
(Oracle cloud). They work fine from a home/residential connection.

Strategy:
1. Try direct fetch first (in case the block has been lifted).
2. If blocked (connection refused, 403 with no body), try curl-cffi
   impersonation (different TLS fingerprint).
3. If still blocked, use nodriver (undetected Chrome) — different browser
   fingerprint may not trigger the IP filter.
4. If all fail, record as BLOCKED outcome for manual lane.

Counties: Rutherford, Lee
"""
from __future__ import annotations

import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_COUNTY_SITES = {
    "rutherford": {
        "url": "https://www.rutherfordcountync.gov/departments/tax",
        "state": "NC",
    },
    "lee": {
        "url": "https://www.leecountync.gov/departments/tax",
        "state": "NC",
    },
}


class DcIpBlockScraper(BaseScraper):
    """Datacenter-IP-blocked NC tax sites — try all tiers, record BLOCKED."""

    slug = "counties_nc.dc_ip_block"
    name = "DC IP Blocked Sites"
    category = "tax"
    timeout_s = 300.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        for county, cfg in _COUNTY_SITES.items():
            try:
                base_url = cfg["url"]
                log.info("dc_ip_block.trying", county=county)

                # Tier 1: plain httpx
                html = await get_text(base_url, timeout=15.0)

                if not html or len(html) < 500:
                    # Tier 2: curl-cffi impersonation
                    html = await get_text(
                        base_url, impersonate=True, timeout=15.0)

                if not html or len(html) < 500:
                    # Tier 3: Playwright (real browser, may bypass IP filter)
                    try:
                        from playwright.async_api import async_playwright
                        async with async_playwright() as p:
                            browser = await p.chromium.launch(
                                headless=True,
                                args=["--no-sandbox", "--disable-gpu"],
                            )
                            pg = await browser.new_page()
                            await pg.goto(base_url, timeout=30000)
                            html = await pg.content()
                            await browser.close()
                    except Exception as exc:
                        log.warning("dc_ip_block.playwright_failed",
                                    county=county, error=str(exc)[:120])

                if not html or len(html) < 500:
                    # Tier 4: wall_bypass (pydoll + nodriver)
                    from ...wall_bypass import fetch_with_nodriver
                    html = await fetch_with_nodriver(base_url, timeout_s=30)

                if not html or len(html) < 500:
                    log.warning("dc_ip_block.blocked",
                                county=county,
                                note="Datacenter IP refused by firewall. "
                                     "Needs residential proxy or manual lane.")
                    continue

                # Parse for tax/foreclosure data
                soup = BeautifulSoup(html, "html.parser")
                rows = soup.select("table tr, .property-list .item")

                for row in rows[1:]:
                    cells = row.find_all("td")
                    if len(cells) < 2:
                        continue

                    parcel_id = cells[0].get_text(strip=True)
                    addr = cells[1].get_text(strip=True) if len(cells) > 1 else ""

                    if not parcel_id and not addr:
                        continue

                    results.append(Listing(
                        source=self.slug,
                        source_url=base_url,
                        listing_type=ListingType.TAX_LIEN,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=addr,
                        county=county.title(),
                        state=cfg["state"],
                        parcel_id=parcel_id,
                        raw={"county": county, "ip_block_resolved": True},
                    ))

                log.info("dc_ip_block.county_done",
                         county=county, found=len(results))

            except Exception as exc:
                log.warning("dc_ip_block.county_error",
                            county=county, error=str(exc)[:200])

        return results
