"""NC Courthouse Computer Systems deeds — Cloudflare-walled.

gastonnc.courthousecomputersystems.com and similar host deed search for
multiple NC counties behind Cloudflare "Just a moment" challenge.

The enrichment_gaston_rod module proves curl_cffi can reach these sites
with Chrome TLS impersonation. We use the same approach here.

Counties: Gaston, Alleghany, Caldwell, Franklin, Hertford, Gates

2026-10-13 source-completeness audit (Pattern C re-check) — live-verified,
TWO separate findings, neither an owner-login issue:

1. ``_fetch_page``'s search URL (``{base}/search/?doctype=DEED&fromdate=...
   &todate=...``) is NOT A REAL ROUTE on any of the 6 real hosts — it was
   never verified against the live app. This is the SAME DevExpress
   "LRSearch" MVC app enrichment_gaston_rod.py's own docstring already names
   ("a CourthouseComputerSystems MVC / DevExpress app"), not the classic-ASP
   SearchService.asp app rod/cchs.py's 5 different counties (Burke/
   Cleveland/Lincoln/Madison/Henderson) use — this module has never shared
   code or a verified endpoint with either of those. So every run of this
   scraper has returned 0 rows for ALL 6 counties, for a different reason
   than the module name suggests: not (only) Cloudflare, but a guessed URL
   that 404s even when Cloudflare lets a request through.

2. Live-verified (browser + curl_cffi, both independently) the 6 real hosts
   split into two genuinely different categories:
     * gastonnc, alleghanync — blocked by a Cloudflare JS/managed challenge
       at the ROOT page, confirmed with BOTH a real rendering browser
       (never clears in 20+s) AND curl_cffi Chrome-impersonation (403 on
       the "Just a moment..." challenge page). This is the genuine
       Cloudflare wall the module name describes — _fetch_page's existing
       Playwright + enrichment_waf_oss fallback is the right tool for it
       (same approach nc_rowan_cott.py and sc_rod_walled.py use), just
       never reached because the URL above fails first.
     * caldwellnc, franklinnc, hertfordnc, gatesnc — curl_cffi clears the
       root page cleanly (200, real HTML) and the real search lives at
       ``POST /LRSearch/ExecuteSearch`` on a 3-step session-seeded flow
       (GET / -> GET /LRSearch/LRIndex?searchTabID=0 -> POST ExecuteSearch),
       the exact same shape enrichment_gaston_rod.py already proves works
       for a NAME search on this app family. A live-captured real
       ``AdvancedFromDate``/``AdvancedToDate`` date-range body (browser
       network capture, no name filled in) is the right shape for what
       this scraper wants — BUT every live attempt against it (5 separate
       POSTs, date windows from 3 to 29 days) came back Cloudflare 524
       ("A timeout occurred" — the origin itself never answered in time),
       including a request left to hang 40+s with no response at all. This
       reproduced on every attempt regardless of window size, so it reads
       as a genuine backend reliability limit of the no-name "Advanced"
       search path on this app, not a parameter-guessing problem on this
       end. enrichment_gaston_rod.py's own (fast, reliable, DEFAULT-ON
       production) NAME search on the identical endpoint strongly suggests
       the backend can't (or won't) run this query shape with no name
       filter in reasonable time — a real site-side limitation, not
       something a better request fixes.

Given #2 could not be verified end-to-end even once in this session despite
using the real, correct endpoint (as opposed to a plausible-looking guess),
the fetch mechanism is intentionally left UNCHANGED here rather than ship an
unverified rewrite — same precedent as this file's own sibling
cash_buyer_deeds.py._cott_recent (Polk): "NOT fixed this batch rather than
ship an unverified guess; left as a confirmed, scoped gap for a follow-up
session instead of a mysterious silent zero." A future session with a
confirmed-working date-range request against ExecuteSearch (or a narrower
scope, like per-owner-name lookups the way enrichment_gaston_rod.py already
does) should replace _fetch_page's search_url construction entirely for
caldwell/franklin/hertford/gates, and keep the Playwright+WAF-solver path for
gaston/alleghany.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from bs4 import BeautifulSoup

from ...base_scraper import BaseScraper, OUTCOME_BLOCKED, OUTCOME_OK
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://{subdomain}.courthousecomputersystems.com"

_COUNTY_SITES = {
    "gaston": {"subdomain": "gastonnc", "state": "NC"},
    "alleghany": {"subdomain": "alleghanync", "state": "NC"},
    "caldwell": {"subdomain": "caldwellnc", "state": "NC"},
    "franklin": {"subdomain": "franklinnc", "state": "NC"},
    "hertford": {"subdomain": "hertfordnc", "state": "NC"},
    "gates": {"subdomain": "gatesnc", "state": "NC"},
}

_HDRS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
}


class NcCchsDeedsScraper(BaseScraper):
    """NC Courthouse Computer Systems deed search via curl_cffi."""

    slug = "counties_nc.nc_cchs_deeds"
    name = "NC CCHS Deeds"
    category = "rod"
    timeout_s = 600.0

    async def fetch(self) -> list[Listing]:
        results: list[Listing] = []
        cutoff = (datetime.now() - timedelta(days=90)).strftime("%m/%d/%Y")
        end_date = datetime.now().strftime("%m/%d/%Y")

        for county, cfg in _COUNTY_SITES.items():
            try:
                base = _BASE.format(subdomain=cfg["subdomain"])
                # KNOWN WRONG, left unchanged this session (see module
                # docstring, 2026-10-13 audit): this path does not exist on
                # the real DevExpress "LRSearch" app any of these 6 hosts
                # run; the real search is POST {base}/LRSearch/ExecuteSearch
                # on a 3-step session-seeded flow, live-verified reachable
                # for caldwell/franklin/hertford/gates but reproducibly
                # Cloudflare-524-timing-out on every attempt with no name
                # filter -- not confidently fixable this session, so not
                # rewritten rather than ship an unverified guess.
                search_url = f"{base}/search/?doctype=DEED&fromdate={cutoff}&todate={end_date}"

                log.info("nc_cchs.fetching", county=county)

                html = await self._fetch_page(base, search_url)

                if not html or len(html) < 500:
                    log.warning("nc_cchs.empty", county=county)
                    continue

                if "just a moment" in html.lower() or "challenge" in html.lower():
                    log.warning("nc_cchs.cloudflare_blocked", county=county)
                    continue

                soup = BeautifulSoup(html, "html.parser")
                rows = soup.select("table.results tr, table.grid tr, .search-result")

                for row in rows[1:]:
                    cells = row.find_all("td")
                    if len(cells) < 4:
                        continue

                    book_page = cells[0].get_text(strip=True)
                    filing_date = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                    doc_type = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                    grantor = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                    grantee = cells[4].get_text(strip=True) if len(cells) > 4 else ""

                    results.append(Listing(
                        source=self.slug,
                        source_url=base,
                        listing_type=ListingType.UNKNOWN,
                        property_kind=PropertyKind.UNKNOWN,
                        county=county.title(),
                        state=cfg["state"],
                        case_number=book_page,
                        owner_name=grantee,
                        plaintiff=grantor,
                        raw={
                            "county": county,
                            "doc_type": doc_type,
                            "filing_date": filing_date,
                            "grantor": grantor,
                            "grantee": grantee,
                            "book_page": book_page,
                        },
                    ))

                log.info("nc_cchs.county_done", county=county, found=len(results))

            except Exception as exc:
                log.warning("nc_cchs.county_error", county=county, error=str(exc)[:200])

        return results

    async def _fetch_page(self, base: str, search_url: str) -> str | None:
        """Fetch page using curl_cffi with Chrome TLS impersonation.

        Uses the same 3-step session approach as enrichment_gaston_rod:
        1. GET / to get session cookie
        2. GET search page to seed session
        3. GET search results URL
        """
        try:
            from curl_cffi import requests as cc_requests

            # Step 1: seed session
            session = cc_requests.Session(impersonate="chrome")
            r = session.get(base + "/", headers=_HDRS, timeout=30,
                            allow_redirects=True)

            # Step 2: load search page
            r = session.get(search_url, headers=_HDRS, timeout=30,
                            allow_redirects=True)

            if r.status_code == 200 and len(r.text) > 500:
                return r.text

            log.warning("nc_cchs.curl_cffi_status",
                        status=r.status_code, size=len(r.text))
        except Exception as exc:
            log.warning("nc_cchs.curl_cffi_error", error=str(exc)[:160])

        # Fallback: Playwright with WAF solver
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-gpu"],
                )
                page = await browser.new_page()
                await page.goto(search_url, timeout=45000)

                try:
                    from ...enrichment_waf_oss import solve_waf_via_browser
                    solved = await solve_waf_via_browser(page)
                    if solved:
                        await page.wait_for_load_state(
                            "networkidle", timeout=20000
                        )
                except Exception as exc:
                    log.warning("nc_cchs.waf_error", error=str(exc)[:160])

                html = await page.content()
                await browser.close()

                if html and len(html) > 500:
                    return html
        except Exception as exc:
            log.warning("nc_cchs.playwright_error", error=str(exc)[:160])

        return None
