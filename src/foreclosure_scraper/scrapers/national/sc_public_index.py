"""SC Public Index scraper — searches foreclosure cases across SC counties.

Source: https://publicindex.sccourts.org/<county>/publicindex/

SC foreclosure cases are filed as Common Pleas (CP) — case format YYYYCPNNNNNNN.
The search form uses ASP.NET WebForms with a disclaimer/accept flow + NoBot extender.

Two paths:
  Charleston: uses jcmsweb.charlestoncounty.org — NOT behind F5/Varnish, curl-cffi works.
  All other counties: behind F5 BIG-IP JS challenge + Varnish WAF. curl-cffi and
    Playwright both fail. nodriver (undetected Chrome) passes the F5 challenge,
    accepts the disclaimer, and successfully submits the ASP.NET search form.

Flow for non-Charleston:
1. nodriver opens the disclaimer page (F5 JS challenge auto-solved by real Chrome)
2. Click the disclaimer accept button
3. Fill last name field via JS, blur to trigger NoBot state
4. Click search button via document.querySelector
5. Parse GridView results table for CP cases

Counties in our SC footprint:
  Spartanburg, Greenville, Pickens, Oconee, Anderson, Cherokee, Laurens,
  Union, Newberry, Abbeville, Greenwood, McCormick, Edgefield, Saluda,
  York, Chester, Chesterfield, Lancaster, Fairfield, Kershaw, Richland,
  Sumter, Lee, Darlington, Dillon, Marlboro, Marion, Horry, Georgetown,
  Williamsburg, Clarendon, Beaufort, Jasper, Colleton, Hampton, Allendale,
  Bamberg, Barnwell, Aiken, Lexington, Calhoun, Orangeburg, Dorchester,
  Berkeley, Charleston
"""

from __future__ import annotations

import asyncio
import re
import time
import structlog
from typing import Any

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# All SC counties with public index sites
SC_COUNTIES = [
    "spartanburg", "greenville", "pickens", "oconee", "anderson",
    "cherokee", "laurens", "union", "newberry", "abbeville",
    "greenwood", "mccormick", "edgefield", "saluda", "york",
    "chester", "chesterfield", "lancaster", "fairfield", "kershaw",
    "richland", "sumter", "lee", "darlington", "dillon",
    "marlboro", "marion", "horry", "georgetown", "williamsburg",
    "clarendon", "beaufort", "jasper", "colleton", "hampton",
    "allendale", "bamberg", "barnwell", "aiken", "lexington",
    "calhoun", "orangeburg", "dorchester", "berkeley", "charleston",
]

# Common last name prefixes to search (covers vast majority of population)
SEARCH_PREFIXES = [
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J",
    "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T",
    "U", "V", "W", "X", "Y", "Z",
]

# Delay between county searches (seconds)
REQUEST_DELAY = 2.0

# Max results per county search (the site caps at ~2500)
MAX_RESULTS_PER_SEARCH = 2500


def _parse_search_results(html: str) -> list[dict[str, str]]:
    """Parse search result table rows into case records."""
    tree = HTMLParser(html)
    results = []
    grids = tree.css("table")
    for grid in grids:
        rows = grid.css("tr")
        if len(rows) < 3:
            continue
        for row in rows:
            cells = row.css("td")
            if len(cells) < 3:
                continue
            try:
                name = cells[0].text().strip() if len(cells) > 0 else ""
                role = cells[1].text().strip() if len(cells) > 1 else ""
                case_number = cells[2].text().strip() if len(cells) > 2 else ""
                date_filed = cells[3].text().strip() if len(cells) > 3 else ""
                status = cells[4].text().strip() if len(cells) > 4 else ""
                date_disposed = cells[5].text().strip() if len(cells) > 5 else ""

                # Only keep CP (Common Pleas) cases — that's where foreclosures live
                if not re.search(r"\d{4}CP\d+", case_number):
                    continue

                results.append({
                    "name": name,
                    "role": role,
                    "case_number": case_number,
                    "date_filed": date_filed,
                    "status": status,
                    "date_disposed": date_disposed,
                })
            except Exception:
                continue
    return results


def _get_hidden_fields(html: str) -> dict[str, str]:
    """Extract all ASP.NET hidden form fields from HTML."""
    tree = HTMLParser(html)
    fields = {}
    for inp in tree.css('input[type="hidden"]'):
        name = inp.attributes.get("name", "")
        val = inp.attributes.get("value", "")
        if name:
            fields[name] = val or ""
    return fields


async def _nodriver_search_county(county: str) -> list[dict[str, str]]:
    """Search one non-Charleston county using nodriver (undetected Chrome).

    nodriver passes the F5 BIG-IP JS challenge, accepts the disclaimer,
    and submits the ASP.NET search form with NoBot extender.
    """
    import nodriver as uc

    base_url = f"https://publicindex.sccourts.org/{county}/publicindex/"

    all_results: list[dict[str, str]] = []

    try:
        # Try headless first (8GB-safe). If F5 blocks it, fall back.
        try:
            browser = await uc.start(headless=True)
        except Exception:
            browser = await uc.start(headless=False)
        page = await browser.get(base_url)
        # Wait for F5 JS challenge to resolve
        await asyncio.sleep(12)

        # Accept disclaimer — click first button found
        btn = await page.find("button", best_match=True)
        if not btn:
            # Try finding by text
            btn = await page.find("Accept", best_match=True)
        if btn:
            await btn.click()
            await asyncio.sleep(8)
        else:
            # Maybe already past disclaimer, check if form is present
            html = await page.get_content()
            if "TextBoxlastName" not in html and "ContentPlaceHolder1_TextBoxlastName" not in html:
                log.warning("sc_public_index.no_disclaimer_button", county=county)
                browser.stop()
                return []

        # Verify we're on the search page
        html = await page.get_content()
        if "ContentPlaceHolder1_TextBoxlastName" not in html:
            log.warning("sc_public_index.no_form", county=county, page_size=len(html))
            browser.stop()
            return []

        # Search each prefix
        for prefix in SEARCH_PREFIXES:
            # Fill last name field via JS
            await page.evaluate(f"""
                var el = document.getElementById('ContentPlaceHolder1_TextBoxlastName');
                if (el) {{ el.value = '{prefix}'; }}
            """)
            await asyncio.sleep(0.5)

            # Blur to trigger NoBot state calculation
            await page.evaluate(
                "document.getElementById('ContentPlaceHolder1_TextBoxlastName').blur();"
            )
            await asyncio.sleep(2)

            # Click search button via JS
            await page.evaluate("""
                var btn = document.querySelector('input[name="ctl00$ContentPlaceHolder1$ButtonSearch"]');
                if (btn) { btn.click(); }
            """)
            await asyncio.sleep(8)

            # Parse results
            html2 = await page.get_content()
            page_results = _parse_search_results(html2)
            all_results.extend(page_results)

            log.info("sc_public_index.prefix_done", county=county,
                     prefix=prefix, cases=len(page_results))

            await asyncio.sleep(REQUEST_DELAY)

        browser.stop()

    except Exception as exc:
        log.error("sc_public_index.nodriver_error",
                  county=county, error=str(exc)[:200])
        try:
            browser.stop()
        except Exception:
            pass
        return []

    # Deduplicate by case number
    seen = set()
    deduped = []
    for r in all_results:
        cn = r.get("case_number", "")
        if cn and cn not in seen:
            seen.add(cn)
            deduped.append(r)
    return deduped


async def _curl_search_county(county: str) -> list[dict[str, str]]:
    """Search Charleston county using curl-cffi (not behind F5/Varnish)."""
    from curl_cffi import requests as cf

    base_url = "https://jcmsweb.charlestoncounty.org/PublicIndex/"
    search_url = "https://jcmsweb.charlestoncounty.org/PublicIndex/PISearch.aspx"

    results = []
    try:
        session = cf.Session()

        # Step 1: GET disclaimer page
        r1 = session.get(base_url, impersonate="chrome", timeout=15)
        if r1.status_code != 200:
            return []

        hidden = _get_hidden_fields(r1.text)
        hidden["ctl00$ContentPlaceHolder1$ButtonAccept"] = "Accept"

        # Step 2: POST accept
        r2 = session.post(base_url, data=hidden, impersonate="chrome",
                          timeout=15, allow_redirects=True)
        if r2.status_code != 200:
            return []

        search_hidden = _get_hidden_fields(r2.text)
        if not search_hidden:
            return []

        # Step 3: Search by last name prefix
        for prefix in SEARCH_PREFIXES:
            search_data = dict(search_hidden)
            search_data["ctl00$ContentPlaceHolder1$TextBoxlastName"] = prefix
            search_data["ctl00$ContentPlaceHolder1$ButtonSearch"] = "Search"
            search_data["ctl00$ContentPlaceHolder1$IndexGroup"] = "rbIndexGroup1"

            try:
                r3 = session.post(search_url, data=search_data,
                                  impersonate="chrome", timeout=30)
                if r3.status_code != 200:
                    continue

                page_results = _parse_search_results(r3.text)
                results.extend(page_results)
                search_hidden = _get_hidden_fields(r3.text)
                await asyncio.sleep(REQUEST_DELAY)
            except Exception:
                continue

    except Exception as exc:
        log.error("sc_public_index.curl_error", county=county, error=str(exc)[:200])
        return []

    # Deduplicate
    seen = set()
    deduped = []
    for r in results:
        cn = r.get("case_number", "")
        if cn and cn not in seen:
            seen.add(cn)
            deduped.append(r)
    return deduped


class SCPublicIndexScraper(BaseScraper):
    """Scrapes SC county public index for foreclosure (Common Pleas) cases.

    Uses nodriver (undetected Chrome) for non-Charleston counties that are
    behind F5 BIG-IP + Varnish WAF. Uses curl-cffi for Charleston which has
    its own subdomain not behind F5.
    """

    slug = "national.sc_public_index"
    requires_render = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._counties = SC_COUNTIES

    async def fetch(self) -> list[Listing]:
        """Search all SC counties for CP (foreclosure) cases."""
        all_results: list[dict[str, str]] = []
        county_counts: dict[str, int] = {}

        for county in self._counties:
            if county == "charleston":
                county_results = await _curl_search_county(county)
            else:
                county_results = await _nodriver_search_county(county)

            county_counts[county] = len(county_results)
            all_results.extend(county_results)
            log.info("sc_public_index.county_done", county=county,
                     cp_cases=len(county_results))

        log.info("sc_public_index.complete",
                 total_cp_cases=len(all_results),
                 county_counts=county_counts)

        # Convert CP cases to Listings
        listings = self._to_listings(all_results, county_counts)
        log.info("sc_public_index.listings_built", count=len(listings))
        return listings

    def _to_listings(self, cases: list[dict[str, str]],
                    county_counts: dict[str, int] | None = None) -> list[Listing]:
        """Convert CP case records to Listing objects."""
        # Build a reverse lookup: case_number -> county
        case_to_county: dict[str, str] = {}
        if county_counts:
            # We don't track which county each case came from separately,
            # so use the case_number prefix mapping
            pass

        listings = []
        for case in cases:
            case_num = case.get("case_number", "")
            if not case_num:
                continue

            # Extract year from case number (YYYYCP...)
            year_match = re.match(r"(\d{4})CP", case_num)
            year = int(year_match.group(1)) if year_match else 2026

            # Only keep recent cases (2024+)
            if year < 2024:
                continue

            name = case.get("name", "")
            role = case.get("role", "")
            date_filed = case.get("date_filed", "")
            status = case.get("status", "")

            li = Listing(
                source=self.slug,
                source_url="https://publicindex.sccourts.org/",
                listing_type=ListingType.LIS_PENDENS,
                property_kind=PropertyKind.UNKNOWN,
                state="SC",
                county=None,
                case_number=case_num,
                raw={
                    "sc_public_index": {
                        "name": name,
                        "role": role,
                        "case_number": case_num,
                        "date_filed": date_filed,
                        "status": status,
                        "court": "SC Common Pleas",
                        "source": "publicindex.sccourts.org",
                    }
                },
            )
            listings.append(li)
        return listings
