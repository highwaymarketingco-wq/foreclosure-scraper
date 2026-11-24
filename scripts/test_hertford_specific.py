#!/usr/bin/env python3
"""Test Hertford county specifically - only one that might work."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.scrapers.counties_nc.nc_ccs_name_search import (
    NcCcsNameSearchScraper, _COUNTIES, _BASE
)
import httpx
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
import structlog

log = structlog.get_logger()


async def test_hertford_only():
    """Test just Hertford with real search."""
    
    base = _BASE.format(subdomain="hertfordnc")
    
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        # 1. Test base URL
        resp = await client.get(f"{base}/")
        log.info("base_test", status=resp.status_code)
        
        if resp.status_code != 200:
            log.error("base_failed", status=resp.status_code)
            return []
        
        # 2. Try the 3-step session for ONE surname
        surname = "SMITH"  # Most common
        
        # Step 1: Seed session
        log.info("step1_seed", url=f"{base}/")
        resp1 = await client.get(f"{base}/")
        
        # Step 2: LRIndex
        log.info("step2_index", url=f"{base}/LRSearch/LRIndex")
        resp2 = await client.get(f"{base}/LRSearch/LRIndex")
        
        # Step 3: ExecuteSearch
        payload = {
            "SearchOnInstruments": "true",
            "RecordingDateStart": "",
            "RecordingDateEnd": "",
            "InstrumentNameSearch": surname,
        }
        
        log.info("step3_search", url=f"{base}/LRSearch/ExecuteSearch", surname=surname)
        resp3 = await client.post(f"{base}/LRSearch/ExecuteSearch", data=payload)
        
        log.info("search_complete", status=resp3.status_code, content_len=len(resp3.text))
        
        # Try to parse response
        try:
            data = resp3.json()
            instruments = data.get("Instruments", [])
            log.info("✅ GOT RESULTS", count=len(instruments))
            
            if instruments:
                log.info("first_result", instrument=str(instruments[0])[:200])
                return instruments
        except Exception as exc:
            log.error("parse_failed", error=str(exc), preview=resp3.text[:500])
        
        return []


if __name__ == "__main__":
    asyncio.run(test_hertford_only())
