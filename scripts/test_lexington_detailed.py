#!/usr/bin/env python3
"""Test Lexington with DETAILED logging to see what's actually happening."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.scrapers.counties_sc.lexington_probate import LexingtonProbateScraper
import structlog

# Enable DEBUG logging
import logging
logging.basicConfig(level=logging.DEBUG)

async def test_with_logs():
    scraper = LexingtonProbateScraper()
    
    print("=" * 80)
    print("🔥 TESTING LEXINGTON PROBATE WITH DETAILED LOGGING")
    print("=" * 80)
    
    try:
        results = await scraper.fetch()
        
        print("=" * 80)
        print(f"RESULTS: {len(results)} listings")
        print("=" * 80)
        
        if results:
            for i, r in enumerate(results[:3]):
                print(f"\n{i+1}. {r}")
        else:
            print("\n❌ NO RESULTS - CHECK LOGS ABOVE FOR WHY")
            
    except Exception as exc:
        print(f"\n💥 EXCEPTION: {exc}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_with_logs())
