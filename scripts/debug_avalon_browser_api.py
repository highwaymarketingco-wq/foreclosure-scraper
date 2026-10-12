"""Avalon/Catalis test — load SPA page via nodriver, then call API from browser context.

Key insight: The CloudFront API returns 403 when called from curl-cffi/httpx,
but if we load the SPA page (lincolncountytax.com) in nodriver first, the
browser will have the correct cookies/origin, and we can call the API via
page.evaluate(fetch(...)).
"""
import asyncio
import json
import re


async def main():
    from foreclosure_scraper.browser_utils import start_browser

    SPA_URL = "https://www.lincolncountytax.com"
    GUID = "a45b9ca6-46be-4396-9468-56194741a38e"
    CLOUDFRONT_BASE = "https://d1ebsyxxbc7tep.cloudfront.net"
    API_URL = f"{CLOUDFRONT_BASE}/data/{GUID}/Wildfire/Records"

    print(f"=== Loading SPA: {SPA_URL} ===")
    browser = await start_browser(headless=False)

    try:
        page = await browser.get(SPA_URL)
        await asyncio.sleep(10)  # Wait for SPA to fully load

        content = await page.get_content()
        print(f"  Page loaded: {len(content)} chars")

        # Check if GUID is in the page
        if GUID in content:
            print(f"  GUID found in page!")
        else:
            guids = re.findall(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', content)
            print(f"  GUIDs found: {guids[:3]}")

        # Use page.evaluate to make the fetch call from the browser
        # nodriver evaluate wraps code as an async function body, so we use
        # a top-level await (no return needed — the last expression is returned)
        print(f"\n=== Calling CloudFront API from browser context ===")
        print(f"  POST: {API_URL}")

        js_fetch = f"""
        (async () => {{
            const resp = await fetch("{API_URL}", {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{value: "a", skip: 0, direct: false}})
            }});
            const status = resp.status;
            const text = await resp.text();
            return JSON.stringify({{status: status, length: text.length, preview: text.substring(0, 500)}});
        }})()
        """

        try:
            result = await page.evaluate(js_fetch, await_promise=True)
            print(f"  Result type: {type(result).__name__}")
            if isinstance(result, str):
                data = json.loads(result)
            else:
                data = result
            if data.get("status") == 200:
                print(f"  SUCCESS! Status 200, {data.get('length', 0)} chars")
                print(f"  Preview: {data.get('preview', '')[:200]}")
            elif data.get("status"):
                print(f"  HTTP {data['status']}, {data.get('length', 0)} chars")
                print(f"  Preview: {data.get('preview', '')[:200]}")
            else:
                print(f"  Error: {data.get('error', 'unknown')}")
        except Exception as e:
            print(f"  Evaluate error: {e}")

        # Try with search term 'smith'
        print(f"\n=== Trying search term 'smith' ===")
        js_fetch2 = f"""
        (async () => {{
            const resp = await fetch("{API_URL}", {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{value: "smith", skip: 0, direct: false}})
            }});
            const text = await resp.text();
            return text;
        }})()
        """

        try:
            full_result = await page.evaluate(js_fetch2, await_promise=True)
            if isinstance(full_result, str) and len(full_result) > 10:
                try:
                    records = json.loads(full_result)
                    if isinstance(records, list):
                        print(f"  Records returned: {len(records)}")
                        if records:
                            print(f"  First record keys: {list(records[0].keys())[:10]}")
                            delinquent = [r for r in records if r.get("isDelinquent")]
                            print(f"  Delinquent records: {len(delinquent)}")
                    elif isinstance(records, dict):
                        print(f"  Response keys: {list(records.keys())[:10]}")
                        if "records" in records:
                            recs = records["records"]
                            print(f"  Records: {len(recs)}")
                except json.JSONDecodeError:
                    print(f"  Not JSON, first 200 chars: {full_result[:200]}")
            else:
                print(f"  Empty or short result: {full_result}")
        except Exception as e:
            print(f"  Evaluate error: {e}")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
