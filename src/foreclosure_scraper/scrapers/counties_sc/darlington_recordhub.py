"""Darlington County SC via Cott Systems RecordHub platform.

Platform: https://recordhub.cottsystems.com/portal/
Coverage: Darlington County SC only (5,854 rows)

This is the ONLY county on the Cott Systems RecordHub platform (unlike
Avenu Insights / CountyFusion which are multi-tenant). Login required with
reCAPTCHA v2 checkbox challenge.

Auth:
  - .secrets/cott_recordhub/email.txt (cashrandolphhigh@gmail.com)
  - .secrets/cott_recordhub/password.txt

Login flow:
  1. GET /Portal/Account/AccountConfirmationLogin for CSRF token
  2. Solve reCAPTCHA v2 checkbox (via enrichment_recaptcha_audio.py)
  3. POST /Portal/Account/Login with UserName, Password, __RequestVerificationToken
  4. Navigate to instrument search grid
  5. Extract recent distress-related instruments (FC, LIS, DEED, etc.)

Returns standard Listing objects with minimal fields (address resolution via
downstream enrichment).
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import structlog
from playwright.async_api import async_playwright, Page, Browser

from ...base_scraper import BaseScraper
from ...enrichment_recaptcha_audio import solve_recaptcha_v2
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://recordhub.cottsystems.com"
_LOGIN_PAGE = f"{_BASE}/Portal/Account/AccountConfirmationLogin"
_LOGIN_POST = f"{_BASE}/Portal/Account/Login"
_SEARCH_URL = f"{_BASE}/Portal/Search"

_SECRETS_DIR = Path(__file__).resolve().parents[4] / ".secrets" / "cott_recordhub"

# Document types that indicate distress
_DISTRESS_DOCTYPES = {
    "FC", "FORECLOSURE", "LIS PENDENS", "LIS", "DEED", "SHERIFF",
    "TAX SALE", "TAX DEED", "MASTER IN EQUITY", "MIE",
}

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _load_credentials() -> tuple[str, str]:
    """Read email/password from secrets directory."""
    email_path = _SECRETS_DIR / "email.txt"
    pass_path = _SECRETS_DIR / "password.txt"
    if not email_path.exists() or not pass_path.exists():
        raise FileNotFoundError(
            f"RecordHub credentials not found at {_SECRETS_DIR}. "
            "Expected email.txt and password.txt."
        )
    email = email_path.read_text().strip()
    password = pass_path.read_text().strip()
    return email, password


async def _login(page: Page) -> bool:
    """Login to RecordHub with reCAPTCHA v2 solving. Returns True on success."""
    try:
        # Step 1: Navigate to login page
        await page.goto(_LOGIN_PAGE, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        
        # Step 2: Extract CSRF token
        token_input = await page.query_selector('input[name="__RequestVerificationToken"]')
        if not token_input:
            log.error("recordhub.no_csrf_token")
            return False
        
        token = await token_input.get_attribute("value")
        if not token:
            log.error("recordhub.empty_csrf_token")
            return False
        
        log.info("recordhub.csrf_token_extracted", token_len=len(token))
        
        # Step 3: Fill credentials
        email, password = _load_credentials()
        
        email_input = await page.query_selector('input[name="UserName"]')
        password_input = await page.query_selector('input[name="Password"]')
        
        if not email_input or not password_input:
            log.error("recordhub.no_login_fields")
            return False
        
        await email_input.fill(email)
        await password_input.fill(password)
        await page.wait_for_timeout(1000)
        
        # Step 4: Solve reCAPTCHA v2
        log.info("recordhub.solving_recaptcha")
        solved = await solve_recaptcha_v2(page, max_retries=3, timeout_ms=60000)
        
        if not solved:
            log.error("recordhub.recaptcha_failed")
            return False
        
        log.info("recordhub.recaptcha_solved")
        await page.wait_for_timeout(1000)
        
        # Step 5: Submit login form
        submit_btn = await page.query_selector('input[type="submit"]')
        if not submit_btn:
            log.error("recordhub.no_submit_button")
            return False
        
        # Wait for navigation after submit
        async with page.expect_navigation(timeout=30000):
            await submit_btn.click()
        
        await page.wait_for_timeout(2000)
        
        # Step 6: Check if login succeeded (should redirect away from Login page)
        current_url = page.url
        if "/Account/Login" in current_url:
            log.error("recordhub.login_failed", url=current_url)
            # Check for error messages
            error_div = await page.query_selector(".validation-summary-errors, .alert-danger")
            if error_div:
                error_text = await error_div.inner_text()
                log.error("recordhub.login_error", error=error_text[:200])
            return False
        
        log.info("recordhub.login_success", url=current_url)
        return True
        
    except Exception as exc:
        log.error("recordhub.login_exception", error=str(exc)[:200])
        return False


async def _search_instruments(page: Page, days_back: int = 90) -> list[dict]:
    """Search for recent instruments and parse results.
    
    This is a placeholder implementation that needs to be customized based on
    the actual search interface once we can access it after login.
    """
    try:
        # Navigate to search page
        await page.goto(_SEARCH_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        
        # Calculate date range
        today = datetime.utcnow()
        from_date = today - timedelta(days=days_back)
        
        # The actual search mechanism will depend on the page structure
        # This is a placeholder that we'll need to update after inspecting
        # the real search interface
        
        # Look for search form elements
        has_search_form = await page.query_selector("form, .search-form, #searchForm")
        if not has_search_form:
            log.warning("recordhub.no_search_form")
            # Try to extract any visible data directly from the page
            return await _extract_instruments_from_page(page)
        
        # Try to find date inputs
        from_date_input = await page.query_selector(
            'input[name*="from" i][type="date"], input[name*="start" i][type="date"]'
        )
        to_date_input = await page.query_selector(
            'input[name*="to" i][type="date"], input[name*="end" i][type="date"]'
        )
        
        if from_date_input and to_date_input:
            await from_date_input.fill(from_date.strftime("%Y-%m-%d"))
            await to_date_input.fill(today.strftime("%Y-%m-%d"))
            
            # Submit search
            search_btn = await page.query_selector(
                'button[type="submit"], input[type="submit"], button:has-text("Search")'
            )
            if search_btn:
                await search_btn.click()
                await page.wait_for_timeout(3000)
        
        # Extract results
        return await _extract_instruments_from_page(page)
        
    except Exception as exc:
        log.error("recordhub.search_exception", error=str(exc)[:200])
        return []


async def _extract_instruments_from_page(page: Page) -> list[dict]:
    """Extract instrument records from the current page.
    
    This needs to be customized based on the actual page structure.
    Common patterns:
    - DataTables grid
    - Simple HTML table
    - JSON API endpoint
    """
    instruments = []
    
    try:
        # Check for DataTables (common in ASP.NET MVC apps)
        has_datatable = await page.evaluate("""() => {
            return typeof jQuery !== 'undefined' && jQuery.fn.DataTable !== undefined;
        }""")
        
        if has_datatable:
            log.info("recordhub.found_datatable")
            # Extract data from DataTable
            rows_data = await page.evaluate("""() => {
                const table = jQuery('table.dataTable').first();
                if (!table.length) return [];
                
                const dt = table.DataTable();
                return dt.rows().data().toArray();
            }""")
            
            if rows_data:
                log.info("recordhub.datatable_rows", count=len(rows_data))
                for row in rows_data:
                    instruments.append(_parse_row_data(row))
            
        else:
            # Fall back to HTML table parsing
            log.info("recordhub.no_datatable_using_html")
            table = await page.query_selector("table")
            if table:
                rows = await table.query_selector_all("tr")
                log.info("recordhub.html_rows", count=len(rows))
                
                for row in rows[1:]:  # Skip header
                    cells = await row.query_selector_all("td")
                    if len(cells) >= 3:
                        cell_texts = []
                        for cell in cells:
                            text = await cell.inner_text()
                            cell_texts.append(text.strip())
                        
                        instruments.append({
                            "raw_cells": cell_texts,
                            "row_html": await row.inner_html(),
                        })
        
    except Exception as exc:
        log.error("recordhub.extract_exception", error=str(exc)[:200])
    
    return instruments


def _parse_row_data(row: Any) -> dict:
    """Parse a row from the DataTable into a structured dict."""
    # This will need to be customized based on actual column structure
    if isinstance(row, dict):
        return row
    elif isinstance(row, (list, tuple)):
        return {"raw_array": list(row)}
    else:
        return {"raw_value": str(row)}


def _build_listing(slug: str, instrument: dict) -> Listing:
    """Build a Listing from an instrument record."""
    # Extract fields - this is a placeholder structure
    # Will need to be updated based on actual data format
    
    case_number = None
    file_date = None
    doc_type = None
    parties = []
    
    # Try to extract from different possible structures
    if "raw_cells" in instrument:
        cells = instrument["raw_cells"]
        if len(cells) > 0:
            case_number = cells[0]
        if len(cells) > 1:
            doc_type = cells[1]
        if len(cells) > 2:
            file_date = cells[2]
    
    # Determine listing type based on document type
    listing_type = ListingType.UNKNOWN
    if doc_type:
        doc_upper = doc_type.upper()
        if any(kw in doc_upper for kw in ["FC", "FORECLOSURE"]):
            listing_type = ListingType.FORECLOSURE_SALE
        elif "LIS PENDENS" in doc_upper or "LIS" in doc_upper:
            listing_type = ListingType.LIS_PENDENS
    
    return Listing(
        source=slug,
        source_url=_SEARCH_URL,
        listing_type=listing_type,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Darlington",
        case_number=case_number,
        raw={
            "recordhub": instrument,
            "doc_type": doc_type,
            "file_date": file_date,
        },
    )


class DarlingtonRecordhub(BaseScraper):
    slug = "counties_sc.darlington_recordhub"
    name = "Darlington County (SC) RecordHub ROD"
    category = "county_rod"
    timeout_s = 600.0  # Generous timeout for reCAPTCHA solving + browser automation
    expected_min_count = 10  # Conservative floor given 5,854 total rows
    
    async def fetch(self) -> Iterable[Listing]:
        """Fetch distress instruments from RecordHub."""
        out = self.partial
        
        async with async_playwright() as p:
            # Launch browser with stealth settings
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]
            )
            
            # Set up context with realistic viewport and user agent
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=_UA,
            )
            
            page = await context.new_page()
            
            try:
                # Login with reCAPTCHA solving
                login_ok = await _login(page)
                if not login_ok:
                    log.error("recordhub.login_failed_aborting")
                    return []
                
                # Search for instruments
                instruments = await _search_instruments(page, days_back=90)
                log.info("recordhub.instruments_found", count=len(instruments))
                
                # Build listings
                for instrument in instruments:
                    try:
                        listing = _build_listing(self.slug, instrument)
                        out.append(listing)
                    except Exception as exc:
                        log.warning(
                            "recordhub.build_listing_failed",
                            error=str(exc)[:120],
                            instrument=str(instrument)[:200]
                        )
                
            finally:
                await context.close()
                await browser.close()
        
        log.info("recordhub.done", total=len(out))
        return list(out)
