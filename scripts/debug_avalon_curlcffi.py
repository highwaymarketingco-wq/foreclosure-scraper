"""Debug: NC Avalon tax CloudFront API with curl-cffi.

The CloudFront API at d1ebsyxxbc7tep.cloudfront.net returns 403 to regular
requests. Try curl-cffi with browser TLS fingerprint to bypass.

Confirmed: 390,627 records behind this endpoint.
"""
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, "src")

# Target API
CLOUDFRONT_BASE = "https://d1ebsyxxbc7tep.cloudfront.net"

# Known county GUIDs (from nc_avalon_tax.py)
COUNTY_GUIDS = {
    "alamance": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",  # placeholder
    # Real GUIDs are extracted from the SPA page
}


async def test_curl_cffi():
    """Try curl-cffi with browser TLS fingerprint."""
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        print("curl_cffi not installed — trying pip install")
        os.system("pip install curl_cffi")
        from curl_cffi import requests as curl_requests

    # Step 1: Get a county SPA page to extract the GUID
    print("=== Step 1: Fetch SPA page to extract GUID ===")

    # Try a known Catalis/Avalon county
    spa_urls = [
        "https://www.catalisgov.com/portal/nc/alamance",
        "https://www.catalisgov.com/portal/nc/wake",
        "https://www.catalisgov.com/portal/nc/durham",
    ]

    guid = None
    for spa_url in spa_urls:
        print(f"\nTrying: {spa_url}")
        try:
            resp = curl_requests.get(spa_url, impersonate="chrome", timeout=30)
            print(f"  Status: {resp.status_code}, Length: {len(resp.text)}")

            # Extract GUID from JavaScript
            guids = re.findall(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', resp.text)
            if guids:
                guid = guids[0]
                print(f"  Found GUID: {guid}")
                break
            else:
                print(f"  No GUID found in page")
        except Exception as e:
            print(f"  Error: {e}")

    if not guid:
        print("\nNo GUID found — trying direct CloudFront API with known patterns")
        # Try direct API call without GUID
        guid = "00000000-0000-0000-0000-000000000000"

    # Step 2: Try CloudFront API with curl-cffi
    print(f"\n=== Step 2: CloudFront API call with GUID: {guid} ===")

    api_url = f"{CLOUDFRONT_BASE}/data/{guid}/Wildfire/Records"
    print(f"POST: {api_url}")

    # Try different impersonation profiles
    for profile in ["chrome", "chrome120", "safari", "edge"]:
        print(f"\n  Profile: {profile}")
        try:
            resp = curl_requests.post(
                api_url,
                json={
                    "SearchType": "Name",
                    "SearchText": "Smith",
                    "RecordType": "ALL",
                    "Page": 1,
                    "PageSize": 50,
                },
                impersonate=profile,
                timeout=30,
                headers={
                    "Origin": "https://www.catalisgov.com",
                    "Referer": "https://www.catalisgov.com/",
                    "Content-Type": "application/json",
                },
            )
            print(f"  Status: {resp.status_code}")
            print(f"  Length: {len(resp.text)}")

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    print(f"  JSON keys: {list(data.keys()) if isinstance(data, dict) else 'array'}")
                    if isinstance(data, dict):
                        records = data.get("Records", data.get("records", data.get("data", [])))
                        print(f"  Records: {len(records) if isinstance(records, list) else 'unknown'}")
                        if isinstance(records, list) and records:
                            print(f"  First record: {json.dumps(records[0], indent=2)[:300]}")
                except Exception:
                    print(f"  Not JSON: {resp.text[:200]}")
            elif resp.status_code == 403:
                print(f"  403 BLOCKED: {resp.text[:200]}")
            else:
                print(f"  Response: {resp.text[:200]}")
        except Exception as e:
            print(f"  Error: {e}")

    # Step 3: Try with nodriver (fully undetected browser)
    print(f"\n=== Step 3: Try nodriver to render SPA and extract data ===")
    try:
        import nodriver as uc

        browser = await uc.start(
            headless=False,
            browser_args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            sandbox=False,
        )
        page = await browser.get(spa_urls[0])
        await asyncio.sleep(15)  # Wait for SPA to load

        content = await page.get_content()
        print(f"  Page content: {len(content)} chars")

        # Check for GUIDs
        guids = re.findall(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', content)
        if guids:
            print(f"  Found GUIDs: {guids[:3]}")

        # Try to execute search via the SPA
        try:
            result = await page.evaluate("""async () => {
                // Look for search input
                const input = document.querySelector('input[type="text"], input[type="search"]');
                if (!input) return "no input found";
                input.value = "Smith";
                input.dispatchEvent(new Event('input', {bubbles: true}));
                // Look for search button
                const btn = document.querySelector('button[type="submit"], .search-btn, .btn-primary');
                if (btn) btn.click();
                return "search triggered";
            }""")
            print(f"  Search: {result}")
            await asyncio.sleep(10)

            # Get page content after search
            content = await page.get_content()
            print(f"  Post-search content: {len(content)} chars")
            with open("/tmp/avalon_nodriver.html", "w") as f:
                f.write(content)
            print(f"  Saved to /tmp/avalon_nodriver.html")
        except Exception as e:
            print(f"  Search error: {e}")

        browser.stop()
    except Exception as e:
        print(f"  nodriver error: {e}")


async def main():
    await test_curl_cffi()
    print("\n=== AVALON TEST COMPLETE ===")


asyncio.run(test_curl_cffi())
