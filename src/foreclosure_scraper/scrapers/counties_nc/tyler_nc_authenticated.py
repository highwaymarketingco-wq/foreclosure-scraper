"""Tyler NC Smart Search — authenticated scraper for foreclosure cases.

Source
------
NC eCourts portal at portal-nc.tylertech.cloud with authenticated Smart Search access.
Unlike the open NCJudgmentSearchService API, this uses credentials to access the full 
Smart Search portal, which includes SP (Special Proceedings) cases — the primary 
foreclosure filing type in NC.

Authentication
--------------
Credentials: 2UUN@ANt7Ki?9)r
Stored at: .secrets/tyler_nc_credentials.txt (password only, username derived)

Target Case Types
-----------------
SP (Special Proceedings) — Power-of-sale foreclosure (NCGS 45-21), partition (NCGS 46A)
CVD (Civil District) — Divorce/equitable distribution (marital home forced sale)
CVS (Civil Superior) — Partition, condemnation
CV (Civil) — Lis pendens, liens

Footprint
---------
NC footprint counties: 11 WNC/foothills + 5 coastal (mirrors nc_ecourts_lis_pendens)
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import structlog
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PORTAL_BASE = "https://portal-nc.tylertech.cloud/Portal"
LOGIN_URL = f"{PORTAL_BASE}/Account/Login"
SEARCH_URL = f"{PORTAL_BASE}/Home/Dashboard/29"  # Smart Search

# NC footprint counties
TARGET_COUNTIES = [
    "Rutherford", "Cleveland", "Henderson", "Polk", "Gaston",
    "Buncombe", "Transylvania", "McDowell", "Lincoln",
    "Mitchell", "Burke",
    # Coastal
    "Brunswick", "Pender", "Onslow", "Carteret", "Dare",
    "Currituck", "Hyde", "New Hanover",
    "Beaufort", "Craven", "Pamlico",
]

# Case type patterns for foreclosure-related cases
FORECLOSURE_CASE_TYPES = [
    "SP",   # Special Proceedings — foreclosure, partition
    "CVD",  # Civil District — divorce
    "CVS",  # Civil Superior — partition
    "CV",   # Civil — lis pendens, liens
]


class TylerNcAuthenticatedScraper(BaseScraper):
    """Tyler NC authenticated Smart Search scraper."""

    slug = "counties_nc.tyler_nc_authenticated"
    name = "Tyler NC Authenticated"
    category = "foreclosure"
    timeout_s = 900.0  # 15 min for authenticated session + searches

    async def fetch(self) -> list[Listing]:
        """Fetch foreclosure cases from Tyler NC using authenticated access."""
        results: list[Listing] = []
        
        # Get credentials
        password = await self._get_password()
        if not password:
            log.error("tyler_nc_auth.no_password")
            return results

        # Username is the email address
        username = "cashrandolphhigh@gmail.com"

        try:
            log.info("tyler_nc_auth.starting", counties=len(TARGET_COUNTIES))
            
            async with async_playwright() as p:
                # Launch browser (headless for VM)
                browser = await p.chromium.launch(
                    headless=True,  # VM requires headless with Xvfb
                    args=["--no-sandbox", "--disable-gpu"],
                )
                
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                
                page = await context.new_page()
                
                # Login
                logged_in = await self._login(page, username, password)
                if not logged_in:
                    log.error("tyler_nc_auth.login_failed")
                    await browser.close()
                    return results

                log.info("tyler_nc_auth.logged_in")

                # Navigate to Smart Search
                await page.goto(SEARCH_URL, timeout=60000, wait_until="networkidle")
                await asyncio.sleep(2)

                # Search each county
                for county in TARGET_COUNTIES:
                    try:
                        county_results = await self._search_county(page, county)
                        results.extend(county_results)
                        log.info("tyler_nc_auth.county_done", 
                                county=county, found=len(county_results))
                        await asyncio.sleep(2)  # Rate limit
                    except Exception as exc:
                        log.warning("tyler_nc_auth.county_error",
                                   county=county, error=str(exc)[:200])

                await browser.close()

            log.info("tyler_nc_auth.complete", total=len(results))

        except Exception as exc:
            log.error("tyler_nc_auth.error", error=str(exc)[:300])

        return results

    async def _get_password(self) -> str:
        """Read password from .secrets file."""
        try:
            # Try project .secrets first
            secrets_path = Path.cwd() / ".secrets" / "tyler_nc_credentials.txt"
            if not secrets_path.exists():
                # Try home directory
                secrets_path = Path.home() / ".secrets" / "tyler_nc_credentials.txt"
            
            if secrets_path.exists():
                return secrets_path.read_text().strip()
            
            # Fallback to direct credential
            return "2UUN@ANt7Ki?9)r"
            
        except Exception as exc:
            log.warning("tyler_nc_auth.password_read_error", error=str(exc))
            return ""

    async def _login(self, page, username: str, password: str) -> bool:
        """Log into Tyler NC portal."""
        try:
            await page.goto(LOGIN_URL, timeout=60000, wait_until="networkidle")
            await asyncio.sleep(1)

            # Fill login form
            await page.fill("input[name='UserName'], input[id='UserName'], input[type='text']", username)
            await page.fill("input[name='Password'], input[id='Password'], input[type='password']", password)
            
            # Click login button
            await page.click("button[type='submit'], input[type='submit'], button:has-text('Log In')")
            
            # Wait for redirect or error
            await asyncio.sleep(3)
            
            # Check if login succeeded (URL changed or dashboard visible)
            current_url = page.url
            if "Dashboard" in current_url or "Home" in current_url:
                return True
            
            # Check for dashboard elements
            dashboard = await page.query_selector(".dashboard, [class*='dashboard'], #dashboard")
            if dashboard:
                return True

            # Check for login error
            error = await page.query_selector(".error, .alert-danger, [class*='error']")
            if error:
                error_text = await error.inner_text()
                log.warning("tyler_nc_auth.login_error_msg", msg=error_text[:200])
                return False

            return False

        except Exception as exc:
            log.error("tyler_nc_auth.login_exception", error=str(exc)[:300])
            return False

    async def _search_county(self, page, county: str) -> list[Listing]:
        """Search for foreclosure cases in a specific county."""
        results: list[Listing] = []
        
        try:
            # Set up search criteria
            # Date range: last 2 years
            end_date = datetime.now()
            start_date = end_date - timedelta(days=730)

            # Click on county filter
            county_filter = await page.query_selector(f"input[value*='{county}'], label:has-text('{county}')")
            if county_filter:
                await county_filter.click()
                await asyncio.sleep(0.5)

            # Set date range
            date_from = await page.query_selector("input[name*='DateFrom'], input[id*='DateFrom']")
            if date_from:
                await date_from.fill(start_date.strftime("%m/%d/%Y"))
            
            date_to = await page.query_selector("input[name*='DateTo'], input[id*='DateTo']")
            if date_to:
                await date_to.fill(end_date.strftime("%m/%d/%Y"))

            # Select case types (SP, CVD, CVS, CV)
            for case_type in FORECLOSURE_CASE_TYPES:
                case_checkbox = await page.query_selector(
                    f"input[value='{case_type}'], input[value*='{case_type}'], label:has-text('{case_type}')"
                )
                if case_checkbox:
                    await case_checkbox.click()
                    await asyncio.sleep(0.3)

            # Submit search
            search_btn = await page.query_selector("button:has-text('Search'), input[type='submit'][value*='Search']")
            if search_btn:
                await search_btn.click()
                await page.wait_for_load_state("networkidle", timeout=30000)
                await asyncio.sleep(2)

            # Parse results
            results.extend(await self._parse_results(page, county))

            # Handle pagination
            page_num = 0
            while page_num < 20:  # Max 20 pages per county
                next_btn = await page.query_selector("a:has-text('Next'), button:has-text('Next'), .pagination .next a")
                if not next_btn:
                    break
                
                is_disabled = await next_btn.get_attribute("disabled")
                if is_disabled:
                    break

                await next_btn.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                await asyncio.sleep(1)

                page_results = await self._parse_results(page, county)
                if not page_results:
                    break
                
                results.extend(page_results)
                page_num += 1

        except Exception as exc:
            log.warning("tyler_nc_auth.search_error", county=county, error=str(exc)[:200])

        return results

    async def _parse_results(self, page, county: str) -> list[Listing]:
        """Parse search results from current page."""
        results: list[Listing] = []
        
        try:
            # Get result rows
            rows = await page.query_selector_all("table.results tr, .search-results tr, .grid-view tr")
            
            for row in rows[1:]:  # Skip header
                try:
                    cells = await row.query_selector_all("td")
                    if len(cells) < 3:
                        continue

                    # Extract case info
                    case_num_elem = cells[0]
                    case_num = (await case_num_elem.inner_text()).strip()
                    
                    if len(cells) > 1:
                        parties_elem = cells[1]
                        parties = (await parties_elem.inner_text()).strip()
                    else:
                        parties = ""
                    
                    if len(cells) > 2:
                        filed_elem = cells[2]
                        filed_date = (await filed_elem.inner_text()).strip()
                    else:
                        filed_date = ""

                    # Parse case type from case number
                    case_type_match = re.search(r'\d{2}([A-Z]+)\d', case_num)
                    case_type = case_type_match.group(1) if case_type_match else ""

                    # Determine listing type
                    listing_type = self._classify_case_type(case_type, case_num)
                    if not listing_type:
                        continue  # Skip non-foreclosure cases

                    # Extract parties
                    plaintiff, defendant = self._parse_parties(parties)

                    # Create listing
                    listing = Listing(
                        source=self.slug,
                        source_url=SEARCH_URL,
                        listing_type=listing_type,
                        county=county,
                        state="NC",
                        case_number=case_num,
                        plaintiff=plaintiff,
                        defendant=defendant,
                        owner_name=defendant,  # Defendant is typically the property owner
                        raw={
                            "case_type": case_type,
                            "filed_date": filed_date,
                            "parties_raw": parties,
                            "nc_ecourts_authenticated": True,
                        },
                    )
                    
                    # Try to parse filed date
                    if filed_date:
                        try:
                            parsed_date = datetime.strptime(filed_date, "%m/%d/%Y")
                            listing.sale_date = parsed_date
                        except ValueError:
                            pass

                    results.append(listing)
                    self.partial.append(listing)

                except Exception as exc:
                    log.warning("tyler_nc_auth.row_parse_error", error=str(exc)[:150])

        except Exception as exc:
            log.warning("tyler_nc_auth.parse_error", error=str(exc)[:200])

        return results

    def _classify_case_type(self, case_type: str, case_num: str) -> Optional[ListingType]:
        """Classify case into appropriate ListingType."""
        case_type_upper = case_type.upper()
        
        if case_type_upper == "SP":
            # Special Proceedings — could be foreclosure or partition
            if "FORECLOS" in case_num.upper():
                return ListingType.FORECLOSURE_SALE
            # Default SP to foreclosure (most common)
            return ListingType.FORECLOSURE_SALE
        
        elif case_type_upper == "CVD":
            # Civil District — typically divorce
            return ListingType.DIVORCE_NOTICE
        
        elif case_type_upper in ("CVS", "CV"):
            # Civil — could be lis pendens, lien, or partition
            return ListingType.LIS_PENDENS
        
        return None

    def _parse_parties(self, parties_text: str) -> tuple[str, str]:
        """Parse plaintiff and defendant from parties text."""
        plaintiff = ""
        defendant = ""
        
        # Common patterns: "Plaintiff v Defendant" or "Plaintiff vs Defendant"
        if " v " in parties_text.lower() or " vs " in parties_text.lower():
            parts = re.split(r'\s+v\.?\s+|\s+vs\.?\s+', parties_text, flags=re.I)
            if len(parts) >= 2:
                plaintiff = parts[0].strip()
                defendant = parts[1].strip()
        elif ":" in parties_text:
            # Another pattern: "Plaintiff: Name, Defendant: Name"
            parts = parties_text.split(",")
            for part in parts:
                if "plaintiff" in part.lower():
                    plaintiff = re.sub(r'plaintiff:?\s*', '', part, flags=re.I).strip()
                elif "defendant" in part.lower():
                    defendant = re.sub(r'defendant:?\s*', '', part, flags=re.I).strip()
        else:
            # Fallback: assume all text is defendant (the owner)
            defendant = parties_text.strip()

        return plaintiff, defendant
