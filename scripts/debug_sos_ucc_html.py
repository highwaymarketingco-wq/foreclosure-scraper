"""Debug NC SOS UCC — save the HTML scrapling gets so we can inspect the form."""
import asyncio
from foreclosure_scraper.scrapers.national.nc_sos_ucc import _fetch_ucc_page, _parse_results

async def main():
    html = await _fetch_ucc_page(days_back=90)
    print(f"HTML length: {len(html)}")
    with open("/tmp/nc_sos_ucc.html", "w") as f:
        f.write(html)
    # Check for key elements
    import re
    for pattern in ["SearchCriteria", "SubmitButton", "submit", "UCC", "Uniform Commercial", "filing", "debtor", "secured"]:
        count = html.lower().count(pattern.lower())
        print(f"  '{pattern}': {count} occurrences")
    # Try parsing
    results = _parse_results(html)
    print(f"Parsed results: {len(results)}")

asyncio.run(main())
