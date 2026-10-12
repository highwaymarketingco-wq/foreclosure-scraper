"""Morganton NC city site — Cloudflare Turnstile on every page.

morgantonnc.gov uses Cloudflare Turnstile challenge.

Strategy: Use Playwright with enrichment_waf_oss solver to bypass
Turnstile. The site has code enforcement and condemned property lists.
"""
from __future__ import annotations

import re

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_URLS = [
    "https://www.morgantonnc.gov/government/code-enforcement/condemned-properties",
    "https://www.morgantonnc.gov/government/code-enforcement",
    "https://www.morgantonnc.gov/government/tax/tax-foreclosures",
]


class MorgantonNcScraper(BaseScraper):
    """Morganton NC — Cloudflare Turnstile via Playwright+WAF solver."""

    slug = "counties_nc.morganton_nc"
    name = "Morganton NC"
    category = "code_enforcement"
    timeout_s = 300.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("morganton_nc.no_playwright")
            return results

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )

            for url in _URLS:
                try:
                    log.info("morganton_nc.fetching", url=url)
                    page = await browser.new_page()
                    await page.goto(url, timeout=45000)

                    # Solve Cloudflare Turnstile/WAF
                    try:
                        from ...enrichment_waf_oss import solve_waf_via_browser
                        solved = await solve_waf_via_browser(page)
                        if solved:
                            log.info("morganton_nc.waf_solved", url=url)
                            await page.wait_for_load_state(
                                "networkidle", timeout=20000
                            )
                    except Exception as exc:
                        log.warning("morganton_nc.waf_error",
                                    url=url, error=str(exc)[:160])

                    html = await page.content()
                    await page.close()

                    if not html or len(html) < 500:
                        log.warning("morganton_nc.empty", url=url)
                        continue

                    soup = BeautifulSoup(html, "html.parser")

                    rows = soup.select(
                        "table tr, .property-list .item, .content table tr"
                    )
                    for row in rows[1:]:
                        cells = row.find_all("td")
                        if len(cells) < 2:
                            continue

                        addr = cells[0].get_text(strip=True)
                        status = cells[1].get_text(strip=True) if len(cells) > 1 else ""

                        if not addr or len(addr) < 5:
                            continue

                        results.append(Listing(
                            source=self.slug,
                            source_url=url,
                            listing_type=ListingType.DISTRESSED,
                            property_kind=PropertyKind.UNKNOWN,
                            street_address=addr,
                            city="Morganton",
                            county="Burke",
                            state="NC",
                            raw={"status": status},
                        ))

                    # Also look for address mentions in the text
                    if not results:
                        text = soup.get_text()
                        addr_pattern = re.compile(
                            r"\b(\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
                            r"(?:St|Street|Ave|Avenue|Blvd|Drive|Dr|Rd|Road|"
                            r"Lane|Ln|Way|Place|Pl|Ct|Court))\b"
                        )
                        for match in addr_pattern.finditer(text):
                            addr = match.group(1)
                            results.append(Listing(
                                source=self.slug,
                                source_url=url,
                                listing_type=ListingType.DISTRESSED,
                                property_kind=PropertyKind.UNKNOWN,
                                street_address=addr,
                                city="Morganton",
                                county="Burke",
                                state="NC",
                                raw={"extracted_from_text": True},
                            ))

                    log.info("morganton_nc.page_done", url=url, found=len(results))

                except Exception as exc:
                    log.warning("morganton_nc.page_error",
                                url=url, error=str(exc)[:200])

            await browser.close()

        return results
