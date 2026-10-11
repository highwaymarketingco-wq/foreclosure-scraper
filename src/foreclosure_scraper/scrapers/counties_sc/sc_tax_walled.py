"""SC tax sites walled by Turnstile/CAPTCHA — Charleston, Dorchester, Georgetown.

sc-charleston.publicaccessnow.com — Cloudflare Turnstile
dorchestercountytaxesonline.com — Google CAPTCHA
georgetowncountytaxesonline.com — Cloudflare Turnstile / Google CAPTCHA

Strategy: Use wall_bypass escalation (curl-cffi → pydoll for Turnstile → nodriver)
to fetch the delinquent tax list pages, then parse the HTML tables.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_COUNTY_SITES = {
    "charleston": {"url": "https://sc-charleston.publicaccessnow.com", "state": "SC"},
    "dorchester": {"url": "https://www.dorchestercountytaxesonline.com", "state": "SC"},
    "georgetown": {"url": "https://www.georgetowncountytaxesonline.com", "state": "SC"},
}


class ScTaxWalledScraper(BaseScraper):
    """SC tax sites behind Turnstile/CAPTCHA via wall_bypass."""

    slug = "counties_sc.sc_tax_walled"
    name = "SC Tax Walled Sites"
    category = "tax"
    timeout_s = 600.0

    async def _collect(self) -> list[Listing]:
        results: list[Listing] = []

        for county, cfg in _COUNTY_SITES.items():
            try:
                base_url = cfg["url"]
                html = ""

                for path in ["/List/Delinquent", "/delinquent", "/taxsale",
                             "/List/TaxSale", "/search/delinquent"]:
                    url = f"{base_url}{path}"
                    log.info("sc_tax_walled.fetching", county=county, path=path)
                    html = await client.get_text(url, wall_bypass=True, timeout=30.0)
                    if html and len(html) > 500:
                        break

                if not html or len(html) < 500:
                    html = await client.get_text(base_url, wall_bypass=True, timeout=30.0)

                if not html or len(html) < 500:
                    log.warning("sc_tax_walled.empty", county=county)
                    continue

                if "turnstile" in html.lower() or "g-recaptcha" in html.lower():
                    log.info("sc_tax_walled.captcha_detected", county=county)
                    from ...wall_bypass import fetch_with_nodriver
                    html = await fetch_with_nodriver(f"{base_url}/List/Delinquent", timeout_s=45)
                    if not html or len(html) < 500:
                        log.warning("sc_tax_walled.nodriver_failed", county=county)
                        continue

                soup = BeautifulSoup(html, "html.parser")
                rows = soup.select(
                    "table tr, .data-table tr, .delinquent-list .item, "
                    ".search-results tr, .grid-view tr"
                )

                county_results: list[Listing] = []
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

                    if not parcel_id and not addr:
                        continue

                    county_results.append(Listing(
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

                results.extend(county_results)
                log.info("sc_tax_walled.county_done", county=county, found=len(county_results))

            except Exception as exc:
                log.warning("sc_tax_walled.county_error", county=county, error=str(exc)[:200])

        return results
