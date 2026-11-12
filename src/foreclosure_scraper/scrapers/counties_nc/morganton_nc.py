"""Morganton NC city site — DISABLED 2026-10-13, no public data left to scrape.

DEEP-DIVE 2026-10-13: the site restructured entirely since this file was
written -- the old `/government/...` path family is gone. Checked all 3
original URLs against the live site, and then the real replacement for
the one that still exists:

- condemned-properties: NO SUCH PAGE EXISTS ANYWHERE on the current site
  (confirmed via in-site link search + a Google site: search that found
  nothing but unrelated historical mentions of an old condemned jail
  building). Not a stale URL -- the city does not appear to publish a
  condemned-properties list at all currently.
- tax-foreclosures: ALSO does not exist. Confirmed via the Finance
  department's real Tax Division page (morgantonnc.gov/finance/page/
  tax-division) -- it only covers the city property tax rate, nothing
  about foreclosure. Tax foreclosure in NC is a COUNTY function (Burke
  County), not a city one -- there was likely never a real standing page
  here.
- code-enforcement: a real current page DOES exist --
  morgantonnc.gov/development-design-services/page/code-enforcement
  (confirmed genuinely Cloudflare-gated: bare curl 403s even on this
  correct URL; confirmed headless=False loads it (200) vs headless=True
  (403), same pattern as polk_tax.py/nc_rod_captcha.py) -- BUT the page
  itself has ZERO tables and no violations/case list of any kind, just
  department info and a staff directory (confirmed:
  document.querySelectorAll('table').length === 0 on the live page).
  Clearing Cloudflare here would load a real page with nothing to parse.

Net result: all three original targets are dead ends, two because the
page is gone, one because the page exists but was never a data source.
Disabled rather than left to spin up a browser, clear a real Cloudflare
gate, and return 0 rows every single run for no reason -- same category
as nc_sos_ucc (confirmed no public source left, not a wall worth
clearing). If Morganton ever publishes a real violations/condemned list
again, it would need to be found fresh -- nothing here points to where.
"""
from __future__ import annotations

import re

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_URLS = [
    "https://www.morgantonnc.gov/development-design-services/page/code-enforcement",
]


class MorgantonNcScraper(BaseScraper):
    """Morganton NC — no public violations/condemned-properties data exists currently."""

    slug = "counties_nc.morganton_nc"
    name = "Morganton NC"
    category = "code_enforcement"
    timeout_s = 300.0
    disabled = True
    disabled_reason = (
        "confirmed 2026-10-13: condemned-properties and tax-foreclosures pages "
        "no longer exist on the city site (not stale URLs -- genuinely gone); "
        "code-enforcement has a real, live, correctly-Cloudflare-gated page but "
        "zero tables/data of any kind on it, just department contact info. "
        "No public violations list currently published by the city."
    )

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []

        try:
            from patchright.async_api import async_playwright
        except ImportError:
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                log.error("morganton_nc.no_playwright")
                return results

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-gpu"],
            )

            for url in _URLS:
                try:
                    log.info("morganton_nc.fetching", url=url)
                    page = await browser.new_page()
                    await page.goto(url, timeout=60000)

                    # Cloudflare JS challenge — patchright headless=False should
                    # auto-pass it. Just WAIT for it to resolve.
                    # Don't call WAF solver (it looks for canvas/Turnstile which
                    # this site doesn't use).
                    cf_solved = False
                    for attempt in range(5):
                        # Wait for CF challenge to auto-resolve
                        await page.wait_for_timeout(8000)
                        html = await page.content()

                        if "Performing security verification" in html or "Just a moment" in html:
                            log.info("morganton_nc.cf_waiting", url=url, attempt=attempt+1)
                            # Try reloading — sometimes helps trigger the pass
                            if attempt >= 2:
                                try:
                                    await page.reload(wait_until="domcontentloaded", timeout=30000)
                                except Exception:
                                    pass
                            continue

                        cf_solved = True
                        log.info("morganton_nc.cf_solved", url=url, attempt=attempt+1)
                        break

                    if not cf_solved:
                        log.warning("morganton_nc.cf_failed", url=url)
                        await page.close()
                        continue

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
