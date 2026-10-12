"""Debug: Test pydoll and nodriver on morganton + city_of_union URLs.

The existing solve_waf_via_browser returns True but page is still CF interstitial.
Test fetch_with_pydoll and fetch_with_nodriver directly to see if they clear Cloudflare.
"""
import asyncio
import sys
import os

sys.path.insert(0, "src")
os.environ.setdefault("DISPLAY", ":99")

from foreclosure_scraper.wall_bypass import fetch_with_pydoll, fetch_with_nodriver

TARGETS = [
    {
        "name": "morganton_nc",
        "url": "https://www.morgantonnc.gov/departments/police-department/foreclosure-sales",
    },
    {
        "name": "city_of_union",
        "url": "https://www.unionsc.gov/departments/finance/utility-billing/foreclosures",
    },
]


async def test_one(target):
    name = target["name"]
    url = target["url"]
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"URL: {url}")
    print(f"{'='*60}")

    # Test 1: pydoll
    print(f"\n--- pydoll test ---")
    try:
        text = await fetch_with_pydoll(url, timeout_s=60)
        print(f"pydoll result: {len(text)} chars")
        if len(text) < 100:
            print(f"  EMPTY RESULT")
        elif "just a moment" in text.lower() or "challenge" in text.lower():
            print(f"  STILL CLOUDFLARE CHALLENGE")
            # Save for analysis
            with open(f"/tmp/{name}_pydoll_cf.html", "w") as f:
                f.write(text)
        else:
            print(f"  SUCCESS — real content!")
            # Check for foreclosure-related keywords
            lower = text.lower()
            for kw in ["foreclosure", "sale", "auction", "property", "deed", "trust"]:
                if kw in lower:
                    print(f"  Found keyword: '{kw}'")
            with open(f"/tmp/{name}_pydoll_success.html", "w") as f:
                f.write(text)
            print(f"  Saved to /tmp/{name}_pydoll_success.html")
    except Exception as e:
        print(f"  ERROR: {e}")

    await asyncio.sleep(3)

    # Test 2: nodriver
    print(f"\n--- nodriver test ---")
    try:
        text = await fetch_with_nodriver(url, timeout_s=60)
        print(f"nodriver result: {len(text)} chars")
        if len(text) < 100:
            print(f"  EMPTY RESULT")
        elif "just a moment" in text.lower() or "challenge" in text.lower():
            print(f"  STILL CLOUDFLARE CHALLENGE")
            with open(f"/tmp/{name}_nodriver_cf.html", "w") as f:
                f.write(text)
        else:
            print(f"  SUCCESS — real content!")
            lower = text.lower()
            for kw in ["foreclosure", "sale", "auction", "property", "deed", "trust"]:
                if kw in lower:
                    print(f"  Found keyword: '{kw}'")
            with open(f"/tmp/{name}_nodriver_success.html", "w") as f:
                f.write(text)
            print(f"  Saved to /tmp/{name}_nodriver_success.html")
    except Exception as e:
        print(f"  ERROR: {e}")


async def main():
    for target in TARGETS:
        await test_one(target)
        await asyncio.sleep(5)
    print("\n\n=== ALL TESTS COMPLETE ===")


asyncio.run(main())
