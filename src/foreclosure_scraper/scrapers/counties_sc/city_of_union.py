"""City of Union SC — DISABLED 2026-10-13, site rebuilt, no data pages left.

DEEP-DIVE 2026-10-13: all 3 original URLs confirmed dead (live "Page Not
Found" on each, checked directly). The whole site was rebuilt on a
different platform (Apptegy -- a news/events-focused municipal CMS) since
this file was written. Checked the real current site's full nav for any
replacement: no tax, finance, building-codes, or code-enforcement page
exists anywhere -- confirmed by reading every real nav link on the live
homepage (payments/employment/bids/news/events only) AND a Google
site:cityofunion.net search for code enforcement / building codes / tax
delinquent, which returned zero results.

Unlike the Morganton case (where one real page survived, just with no
data on it), City of Union's rebuild dropped the department content
pages entirely -- there is nothing on this domain to point a scraper at
right now, not even a dead end with a maybe-real URL to guess at.

Not a wall worth clearing (no CAPTCHA/WAF involved in this finding at
all -- every URL checked was a plain 404 or absent from the live nav).
If the city ever republishes department pages, this would need a fresh
URL hunt from scratch -- nothing here points to where.
"""
from __future__ import annotations

import re
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_URLS = [
    "https://www.cityofunion.net/departments/finance/tax",
    "https://www.cityofunion.net/departments/building-codes",
    "https://www.cityofunion.net/news",
]


class CityOfUnionScraper(BaseScraper):
    """City of Union SC — site rebuilt, no department/data pages exist currently."""

    slug = "counties_sc.city_of_union"
    name = "City of Union SC"
    category = "municipal"
    timeout_s = 300.0
    disabled = True
    disabled_reason = (
        "confirmed 2026-10-13: all 3 original URLs are dead 404s, the city "
        "rebuilt its site on Apptegy (news/events platform), and no "
        "tax/building-codes/code-enforcement page exists anywhere on the "
        "current site -- confirmed via full nav read + a zero-result Google "
        "site: search. Not a CAPTCHA/WAF wall; the content is simply gone."
    )

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            from patchright.async_api import async_playwright
        except ImportError:
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                log.error("city_of_union.no_playwright")
                return results

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-gpu"],
            )

            for url in _URLS:
                page = None
                try:
                    page = await browser.new_page()
                    log.info("city_of_union.fetching", url=url)

                    await page.goto(url, timeout=45000)

                    # Check for Cloudflare / JS challenge — retry up to 5 times
                    cf_solved = False
                    for attempt in range(5):
                        await page.wait_for_load_state("domcontentloaded", timeout=20000)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=15000)
                        except Exception:
                            pass

                        html = await page.content()
                        if any(kw in html for kw in [
                            "Performing security verification",
                            "Just a moment",
                            "cf-challenge",
                            "Checking your browser",
                        ]):
                            log.info("city_of_union.cf_waiting", url=url, attempt=attempt+1)
                            if attempt >= 2:
                                try:
                                    await page.reload(wait_until="domcontentloaded", timeout=30000)
                                except Exception:
                                    pass
                            await page.wait_for_timeout(8000)
                            continue

                        cf_solved = True
                        break

                    if not cf_solved:
                        log.warning("city_of_union.cf_failed", url=url)
                        await page.close()
                        continue

                    html = await page.content()
                    if not html or len(html) < 500:
                        log.warning("city_of_union.empty", url=url)
                        await page.close()
                        continue

                    soup = BeautifulSoup(html, "html.parser")

                    text = soup.get_text().lower()
                    if any(kw in text for kw in [
                        "foreclosure", "tax sale", "delinquent", "condemned",
                        "surplus", "auction", "sheriff sale"
                    ]):
                        addr_pattern = re.compile(
                            r"\b(\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
                            r"(?:St|Street|Ave|Avenue|Blvd|Drive|Dr|Rd|Road|"
                            r"Lane|Ln|Way|Place|Pl|Ct|Court))\b"
                        )
                        page_text = soup.get_text()
                        for match in addr_pattern.finditer(page_text):
                            addr = match.group(1)
                            results.append(Listing(
                                source=self.slug,
                                source_url=url,
                                listing_type=ListingType.UNKNOWN,
                                property_kind=PropertyKind.UNKNOWN,
                                street_address=addr,
                                city="Union",
                                county="Union",
                                state="SC",
                                raw={"extracted_from_text": True},
                            ))

                    rows = soup.select("table tr")
                    for row in rows[1:]:
                        cells = row.find_all("td")
                        if len(cells) < 2:
                            continue
                        addr = cells[0].get_text(strip=True)
                        if addr and len(addr) > 5:
                            results.append(Listing(
                                source=self.slug,
                                source_url=url,
                                listing_type=ListingType.UNKNOWN,
                                property_kind=PropertyKind.UNKNOWN,
                                street_address=addr,
                                city="Union",
                                county="Union",
                                state="SC",
                                raw={"from_table": True},
                            ))

                    log.info("city_of_union.page_done", url=url, found=len(results))

                except Exception as exc:
                    log.warning("city_of_union.page_error", url=url, error=str(exc)[:200])
                finally:
                    if page:
                        try:
                            await page.close()
                        except BaseException:
                            pass

            await browser.close()

        return results
