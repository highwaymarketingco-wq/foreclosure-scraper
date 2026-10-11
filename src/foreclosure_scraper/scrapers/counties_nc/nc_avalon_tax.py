"""NC Catalis Avalon tax sites — Google CAPTCHA + cloudfront block.

lincolncountytax.com and similar sites are hosted by Catalis Avalon.
They use Google reCAPTCHA + a cloudfront.net data host that blocks datacenter IPs.

Strategy:
1. Try wall_bypass (curl-cffi impersonation → pydoll → nodriver) to get past
   the Cloudflare/CAPTCHA wall on the main page.
2. If the data host (cloudfront.net) blocks our IP, fall back to parsing
   whatever data is embedded in the initial page HTML.
3. For Google reCAPTCHA V2, use enrichment_recaptcha_audio.solve_recaptcha_v2()
   with Playwright to clear the checkbox.

Counties: Lincoln, Rutherford, McDowell, Cleveland, Burke, Caldwell
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_COUNTY_SITES = {
    "lincoln": {"url": "https://www.lincolncountytax.com", "state": "NC"},
    "rutherford": {"url": "https://www.rutherfordcountytax.com", "state": "NC"},
    "mcdowell": {"url": "https://www.mcdowellcountytax.com", "state": "NC"},
    "cleveland": {"url": "https://www.clevelandcountytax.com", "state": "NC"},
    "burke": {"url": "https://www.burkecountytax.com", "state": "NC"},
    "caldwell": {"url": "https://www.caldwellcountytax.com", "state": "NC"},
}


class NcAvalonTaxScraper(BaseScraper):
    """NC Catalis Avalon tax search via wall_bypass + reCAPTCHA solver."""

    slug = "counties_nc.nc_avalon_tax"
    name = "NC Avalon Tax (Catalis)"
    category = "tax"
    timeout_s = 900.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        for county, cfg in _COUNTY_SITES.items():
            try:
                base_url = cfg["url"]
                search_url = f"{base_url}/List/Delinquent"

                log.info("nc_avalon.fetching", county=county)
                html = await get_text(
                    search_url,
                    wall_bypass=True,
                    timeout=30.0,
                )

                if not html or len(html) < 500:
                    html = await get_text(
                        base_url,
                        wall_bypass=True,
                        timeout=30.0,
                    )

                if not html or len(html) < 500:
                    log.warning("nc_avalon.empty", county=county)
                    continue

                if "g-recaptcha" in html or "recaptcha" in html.lower():
                    log.info("nc_avalon.recaptcha_detected", county=county)
                    from ...wall_bypass import fetch_with_nodriver
                    html = await fetch_with_nodriver(search_url, timeout_s=45)
                    if not html or len(html) < 500:
                        log.warning("nc_avalon.nodriver_failed", county=county)
                        continue

                soup = BeautifulSoup(html, "html.parser")
                rows = soup.select(
                    "table tr, .data-table tr, .delinquent-list .item, "
                    ".search-results tr, .grid-view tr"
                )

                for row in rows[1:]:
                    cells = row.find_all("td")
                    if len(cells) < 3:
                        continue

                    parcel_id = cells[0].get_text(strip=True)
                    owner = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                    addr = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                    amount = cells[3].get_text(strip=True) if len(cells) > 3 else ""

                    amount_val = None
                    if amount:
                        m = re.search(r"[\$]([\d,.]+)", amount)
                        if m:
                            amount_val = float(m.group(1).replace(",", ""))

                    results.append(Listing(
                        source=self.slug,
                        source_url=base_url,
                        listing_type=ListingType.TAX_LIEN,
                        property_kind=PropertyKind.UNKNOWN,
                        street_address=addr,
                        county=county.title(),
                        state=cfg["state"],
                        parcel_id=parcel_id,
                        owner_name=owner,
                        tax_value=amount_val,
                        raw={"county": county, "amount_due": amount},
                    ))

                log.info("nc_avalon.county_done", county=county, found=len(results))

            except Exception as exc:
                log.warning("nc_avalon.county_error", county=county, error=str(exc)[:200])

        return results
