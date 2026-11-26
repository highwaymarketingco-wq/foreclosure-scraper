"""York County SC Property Tax scraper via ArcGIS.

DISCOVERED 2026-11-26: York County GIS portal works from VM!

URL: https://experience.arcgis.com/experience/e827d330f20a4508aa6777bf2c0b94e3
Estimated rows: ~406K
Data: Property tax delinquent records

TESTING NEEDED:
- Find property search interface
- Check if CAPTCHA exists
- Test from VM (may need Oracle Cloud IP)
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import structlog
from playwright.async_api import async_playwright

from foreclosure_scraper.base_scraper import BaseScraper
from foreclosure_scraper.listing import Listing

log = structlog.get_logger()

_BASE_URL = "https://experience.arcgis.com/experience/e827d330f20a4508aa6777bf2c0b94e3"


class YorkCountyPropertyTaxScraper(BaseScraper):
    """York County SC property tax via ArcGIS Experience."""

    slug = "sc.york_property_tax"
    name = "York County SC Property Tax"
    category = "property_tax"
    timeout_s = 1800.0

    async def fetch(self) -> list[Listing]:
        """Fetch York County property tax data."""
        results: list[Listing] = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                
                log.info("york.loading_gis_portal")
                await page.goto(_BASE_URL, timeout=60000)
                await asyncio.sleep(15)  # Let ArcGIS Experience fully load
                
                # Get page content
                text = await page.evaluate("document.body.innerText")
                log.info("york.page_loaded", text_length=len(text))
                
                # TODO: Navigate to property search
                # TODO: Check for CAPTCHA
                # TODO: Extract property records
                
                # Placeholder - needs implementation
                log.warning("york.not_implemented", note="Portal loads, needs search automation")
                
            except Exception as exc:
                log.error("york.fetch_failed", error=str(exc)[:300])
            finally:
                await browser.close()
        
        return results
