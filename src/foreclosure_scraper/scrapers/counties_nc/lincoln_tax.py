"""Lincoln County NC Tax - Property search with reCAPTCHA V2.

Spreadsheet impact: 21,069 rows (multi_year_delinquent_tax + heir_naming_publication + quiet_title + usps_vacancy + atty_tax_verified_confirmed).

Source: www.lincolncountytax.com
Platform: Property tax search with reCAPTCHA V2 checkbox
Strategy: Patchright browser with reCAPTCHA audio solver (Groq Whisper)

Same pattern as:
- Lexington probate (lexington_probate.py)
- SC SOS (sc_sos_entity.py)  
- Bertie tax, McDowell tax, Georgetown SC tax (all use reCAPTCHA)

This is a TEMPLATE - copy pattern to other tax portals.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import structlog
from patchright.async_api import async_playwright

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ...enrichment_recaptcha_audio import solve_recaptcha_v2_audio

log = structlog.get_logger()

_URL = "https://www.lincolncountytax.com"
_LOOKBACK_DAYS = 730  # 2 years


class LincolnTax(BaseScraper):
    """Lincoln County NC delinquent tax search with reCAPTCHA solver."""
    
    async def fetch(self) -> Iterable[Listing]:
        """Fetch delinquent tax listings after solving reCAPTCHA."""
        log.info("lincoln_tax.start", url=_URL)
        
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            # Navigate to tax search
            await page.goto(_URL)
            await page.wait_for_load_state("networkidle")
            
            # Look for reCAPTCHA
            recaptcha_frame = page.frame_locator('iframe[src*="recaptcha"]').first
            if recaptcha_frame:
                log.info("lincoln_tax.solving_recaptcha")
                success = await solve_recaptcha_v2_audio(page)
                
                if not success:
                    log.error("lincoln_tax.recaptcha_failed")
                    return []
                
                log.info("lincoln_tax.recaptcha_solved")
            
            # Search for delinquent properties
            # (Adjust selectors based on actual site structure)
            await page.wait_for_timeout(2000)
            
            # Click search/submit
            search_btns = await page.locator('button, input[type="submit"]').all()
            for btn in search_btns:
                try:
                    text = await btn.inner_text() if await btn.is_visible() else ""
                    if "search" in text.lower():
                        await btn.click()
                        break
                except:
                    pass
            
            await page.wait_for_timeout(3000)
            
            # Extract results
            listings = []
            rows = await page.locator('table tr, .property-row').all()
            
            for row in rows[:100]:  # Limit for testing
                try:
                    text = await row.inner_text()
                    if len(text) > 20:
                        # Parse property data (customize based on actual HTML)
                        listings.append(Listing(
                            listing_type=ListingType.TAX_DELINQUENT,
                            county="Lincoln",
                            state="NC",
                            source=_URL,
                            source_name="Lincoln County Tax",
                            property_kind=PropertyKind.REAL,
                            raw_text=text[:500],
                        ))
                except:
                    continue
            
            log.info("lincoln_tax.extracted", count=len(listings))
            return listings
            
        except Exception as e:
            log.error("lincoln_tax.error", error=str(e))
            return []
        finally:
            await browser.close()
            await playwright.stop()
