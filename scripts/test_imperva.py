#!/usr/bin/env python3
"""Test if Greenville/Greenwood Imperva is accessible."""
import httpx

urls = [
    "https://www.greenvillecounty.org/appsas400/Probate/SearchResults.aspx",
    "https://www.greenwoodsc.gov/148/Probate-Court",
]

for url in urls:
    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True)
        print(f"{url}: {resp.status_code}")
        print(f"  Server: {resp.headers.get('Server', 'N/A')}")
        if "incapsula" in resp.text.lower() or "imperva" in resp.text.lower():
            print("  ⚠️  Imperva/Incapsula detected")
        if resp.status_code == 403:
            print("  ❌ 403 Forbidden")
    except Exception as exc:
        print(f"{url}: ERROR - {str(exc)[:100]}")
    print()
