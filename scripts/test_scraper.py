#!/usr/bin/env python3
"""Test individual scrapers to verify fixes."""
import asyncio
import sys
import os

os.environ.setdefault("FORECLOSURE_ROLE", "vm")
os.environ.setdefault("DISPLAY", ":99")

async def test_scraper(module_path):
    """Import and run a scraper module, print results."""
    import importlib
    from foreclosure_scraper.scrapers.base import BaseScraper
    
    mod = importlib.import_module(f"foreclosure_scraper.scrapers.{module_path}")
    
    # Find the BaseScraper subclass
    scraper_class = None
    for name in dir(mod):
        obj = getattr(mod, name)
        if (isinstance(obj, type) and issubclass(obj, BaseScraper) 
                and obj is not BaseScraper and not name.startswith("_")):
            scraper_class = obj
            break
    
    if not scraper_class:
        print(f"No BaseScraper subclass found in {module_path}")
        return 0
    
    s = scraper_class()
    print(f"Running {module_path}...")
    rows = await s.fetch()
    print(f"Result: {len(rows)} rows")
    if rows:
        for r in rows[:3]:
            if hasattr(r, "model_dump"):
                d = r.model_dump()
                print(f"  {d.get('owner_name', 'N/A')} | {d.get('address', 'N/A')} | {d.get('source', 'N/A')}")
            else:
                print(f"  {r}")
    return len(rows)

if __name__ == "__main__":
    scrapers = sys.argv[1:]
    if not scrapers:
        print("Usage: test_scraper.py <module.path> [module.path ...]")
        sys.exit(1)
    
    for scraper in scrapers:
        try:
            count = asyncio.run(test_scraper(scraper))
            print(f"  {scraper}: {count} rows {'✓' if count > 0 else '✗'}")
        except Exception as e:
            print(f"  {scraper}: ERROR - {e}")
