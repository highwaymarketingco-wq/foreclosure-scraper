"""SC tax sites walled by Turnstile/CAPTCHA — Charleston, Dorchester, Georgetown.

sc-charleston.publicaccessnow.com — Cloudflare Turnstile
dorchestercountytaxesonline.com — Google CAPTCHA
georgetowncountytaxesonline.com — Cloudflare Turnstile / Google CAPTCHA

Strategy: Use Playwright + enrichment_waf_oss WAF solver for Turnstile,
or enrichment_recaptcha_audio for reCAPTCHA V2. Then parse delinquent tax lists.
"""
from __future__ import annotations

import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_COUNTY_SITES = {
    "charleston": {
        "url": "https://sc-charleston.publicaccessnow.com",
        "state": "SC",
        "gate": "turnstile",
    },
    "dorchester": {
        "url": "https://www.dorchestercountytaxesonline.com",
        "state": "SC",
        "gate": "recaptcha",
    },
    "georgetown": {
        "url": "https://www.georgetowncountytaxesonline.com",
        "state": "SC",
        "gate": "turnstile",
    },
}


class ScTaxWalledScraper(BaseScraper):
    """SC tax sites behind Turnstile/reCAPTCHA via Playwright + solver."""

    slug = "counties_sc.sc_tax_walled"
    name = "SC Tax Walled Sites"
    category = "tax"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("sc_tax_walled.no_playwright")
            return results

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )

            for county, cfg in _COUNTY_SITES.items():
                page = await browser.new_page()
                try:
                    base_url = cfg["url"]
                    gate = cfg.get("gate", "turnstile")
                    html = ""

                    # Try delinquent list paths
                    for path in [
                        "/List/Delinquent", "/delinquent", "/taxsale",
                        "/List/TaxSale", "/search/delinquent", "/",
                    ]:
                        url = f"{base_url}{path}"
                        try:
                            log.info("sc_tax_walled.fetching", county=county, path=path)
                            await page.goto(url, timeout=30000)
                            await page.wait_for_load_state("networkidle", timeout=10000)

                            # Check if we hit a WAF/CAPTCHA
                            content = await page.content()

                            # Solve Turnstile via WAF solver
                            if gate == "turnstile" or "turnstile" in content.lower():
                                try:
                                    from ...enrichment_waf_oss import solve_waf_via_browser
                                    solved = await solve_waf_via_browser(page)
                                    if solved:
                                        await page.wait_for_load_state("networkidle", timeout=15000)
                                        content = await page.content()
                                except Exception as exc:
                                    log.warning("sc_tax_walled.waf_failed",
                                                county=county, error=str(exc)[:120])

                            # Solve reCAPTCHA V2 via audio
                            if gate == "recaptcha" or "g-recaptcha" in content.lower():
                                try:
                                    from ...enrichment_recaptcha_audio import solve_recaptcha_v2
                                    solved = await solve_recaptcha_v2(page)
                                    if solved:
                                        await page.wait_for_load_state("networkidle", timeout=15000)
                                        content = await page.content()
                                except Exception as exc:
                                    log.warning("sc_tax_walled.recaptcha_failed",
                                                county=county, error=str(exc)[:120])

                            if content and len(content) > 500:
                                html = content
                                break

                        except Exception as exc:
                            log.warning("sc_tax_walled.path_error",
                                        county=county, path=path, error=str(exc)[:120])
                            continue

                    if not html or len(html) < 500:
                        log.warning("sc_tax_walled.empty", county=county)
                        continue

                    # Parse delinquent tax list
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
                    log.info("sc_tax_walled.county_done",
                             county=county, found=len(county_results))

                except Exception as exc:
                    log.warning("sc_tax_walled.county_error",
                                county=county, error=str(exc)[:200])
                finally:
                    await page.close()

            await browser.close()

        return results
