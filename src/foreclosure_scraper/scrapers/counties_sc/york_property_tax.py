"""York County SC Property Tax scraper via ArcGIS.

TESTED 2026-11-26: Works from VM with NO CAPTCHA!

URL: https://experience.arcgis.com/experience/e827d330f20a4508aa6777bf2c0b94e3
Estimated rows: ~406K parcels
Data: Property parcel records (Tax Map IDs, owners, addresses)

TESTED:
✅ Portal loads from VM (Oracle Cloud IP)
✅ NO CAPTCHA detected
✅ Property search interface accessible
✅ Parcel data visible (Tax Map ID, owner names, addresses)

STRATEGY:
- Navigate to Property Search page
- Click "Search Parcels" to load interface
- Use ArcGIS REST API to query all features
- Extract Tax Map ID, owner, address for each parcel
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

import httpx
import structlog
from playwright.async_api import async_playwright

from foreclosure_scraper.base_scraper import BaseScraper
from foreclosure_scraper.models import Listing, ListingType

log = structlog.get_logger()

_BASE_URL = "https://experience.arcgis.com/experience/e827d330f20a4508aa6777bf2c0b94e3"
_PROPERTY_SEARCH = f"{_BASE_URL}/page/Property-Search"


class YorkCountyPropertyTaxScraper(BaseScraper):
    """York County SC property tax via ArcGIS Experience."""

    slug = "sc.york_property_tax"
    name = "York County SC Property Tax"
    category = "property_tax"
    timeout_s = 3600.0  # 1 hour for 406K records

    async def fetch(self) -> list[Listing]:
        """Fetch York County property parcel data."""
        results: list[Listing] = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                
                log.info("york.loading_property_search")
                await page.goto(_PROPERTY_SEARCH, timeout=60000)
                await asyncio.sleep(15)
                
                # Click Search Parcels to open interface
                links = await page.query_selector_all("a, button, [role='button']")
                for el in links:
                    text = await el.inner_text()
                    if "parcel" in text.lower():
                        log.info("york.clicking_search_parcels")
                        await page.evaluate("(el) => el.click()", el)
                        await asyncio.sleep(15)
                        break
                
                # Look for ArcGIS REST API endpoint in network requests
                # ArcGIS Experience apps typically use FeatureServer URLs
                log.info("york.searching_for_api")
                
                # Try to find the data source by inspecting page
                html = await page.content()
                
                # Look for feature service URLs
                feature_urls = re.findall(
                    r'https://[^"\']+/rest/services/[^"\']+/FeatureServer/\d+',
                    html
                )
                
                if feature_urls:
                    log.info("york.found_feature_service", url=feature_urls[0][:100])
                    # Query the feature service directly
                    results = await self._query_feature_service(feature_urls[0])
                else:
                    log.warning("york.no_api_found", note="Extracting from page DOM")
                    # Fall back to scraping visible results
                    results = await self._scrape_page_results(page)
                
                log.info("york.complete", total=len(results))
                
            except Exception as exc:
                log.error("york.fetch_failed", error=str(exc)[:500])
            finally:
                await browser.close()
        
        return results

    async def _query_feature_service(self, service_url: str) -> list[Listing]:
        """Query ArcGIS FeatureServer for all records."""
        results: list[Listing] = []
        
        # ArcGIS REST API query parameters
        query_url = f"{service_url}/query"
        
        # First, get count
        async with httpx.AsyncClient(timeout=60.0) as client:
            count_params = {
                "where": "1=1",
                "returnCountOnly": "true",
                "f": "json"
            }
            
            try:
                resp = await client.get(query_url, params=count_params)
                data = resp.json()
                total_count = data.get("count", 0)
                log.info("york.api_count", total=total_count)
                
                # Query in batches (ArcGIS limit is usually 1000-2000 per request)
                batch_size = 1000
                offset = 0
                
                while offset < total_count:
                    params = {
                        "where": "1=1",
                        "outFields": "*",
                        "returnGeometry": "false",
                        "resultOffset": str(offset),
                        "resultRecordCount": str(batch_size),
                        "f": "json"
                    }
                    
                    resp = await client.get(query_url, params=params)
                    data = resp.json()
                    
                    features = data.get("features", [])
                    log.info("york.api_batch", offset=offset, count=len(features))
                    
                    for feature in features:
                        attrs = feature.get("attributes", {})
                        
                        # Extract fields (adjust based on actual field names)
                        tax_map_id = attrs.get("TaxMapID") or attrs.get("PARCELID") or attrs.get("PIN")
                        owner = attrs.get("OWNER") or attrs.get("OWNERNAME")
                        address = attrs.get("SITEADDRESS") or attrs.get("ADDRESS")
                        
                        if tax_map_id:
                            listing = Listing(
                                source=self.slug,
                                county="York",
                                state="SC",
                                listing_type=ListingType.TAX_LIEN,
                                parcel_id=str(tax_map_id),
                                defendant=owner or "",
                                street_address=address or "",
                                source_url=_PROPERTY_SEARCH,
                            )
                            results.append(listing)
                    
                    offset += batch_size
                    
                    if len(features) < batch_size:
                        break
                    
                    await asyncio.sleep(1)  # Rate limiting
                    
            except Exception as exc:
                log.error("york.api_failed", error=str(exc)[:300])
        
        return results

    async def _scrape_page_results(self, page) -> list[Listing]:
        """Scrape visible results from page as fallback."""
        results: list[Listing] = []
        
        try:
            # Get all visible parcel entries
            content = await page.evaluate("document.body.innerText")
            
            # Parse Tax Map ID and Owner patterns
            # Format: "Tax Map ID: 1830000059 Owner(s): EQUITY TRUST COMPANY..."
            pattern = r"Tax Map ID:\s+(\d+)\s+Owner\(s\):\s+([^\n]+)"
            
            matches = re.findall(pattern, content)
            log.info("york.page_scrape", found=len(matches))
            
            for tax_id, owner in matches:
                listing = Listing(
                    source=self.slug,
                    county="York",
                    state="SC",
                    listing_type=ListingType.TAX_LIEN,
                    parcel_id=tax_id,
                    defendant=owner.strip(),
                    source_url=_PROPERTY_SEARCH,
                )
                results.append(listing)
                
        except Exception as exc:
            log.warning("york.page_scrape_failed", error=str(exc)[:200])
        
        return results
