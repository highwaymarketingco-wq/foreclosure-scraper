"""Debug: NC SOS UCC + SC SOS Entity — test scrapling and nodriver.

nc_sos_ucc: Cloudflare JS challenge on sosnc.gov. Has scrapling fetcher
  with solve_cloudflare=True but disabled. Test if scrapling clears it.

sc_sos_entity: Google reCAPTCHA on sos.sc.gov. Test if we can get past
  the reCAPTCHA checkbox (may auto-pass with patchright stealth).
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, "src")
os.environ.setdefault("DISPLAY", ":99")


async def test_nc_sos_ucc_scrapling():
    """Test scrapling on NC SOS UCC search."""
    print("\n=== NC SOS UCC — scrapling test ===")
    try:
        from scrapling.fetchers import StealthyFetcher

        url = "https://www.sosnc.gov/online_services/search/by_title/_u_cc"
        print(f"Fetching: {url}")

        def page_action(page):
            print("  page_action called — waiting for Cloudflare...")
            import time
            time.sleep(15)
            print("  page_action done")

        # Run scrapling's sync API in a thread to avoid asyncio conflict
        import concurrent.futures
        loop = asyncio.get_event_loop()
        page = await loop.run_in_executor(
            None,
            lambda: StealthyFetcher.fetch(
                url,
                headless=False,
                network_idle=True,
                page_action=page_action,
                solve_cloudflare=True,
                timeout=60000,
            )
        )

        print(f"  Status: {page.status}")
        content = page.html_content
        print(f"  Content length: {len(content)}")

        if "just a moment" in content.lower() or "challenge" in content.lower():
            print("  STILL CLOUDFLARE CHALLENGE")
        elif "search" in content.lower() or "ucc" in content.lower():
            print("  SUCCESS — real content!")
            with open("/tmp/nc_sos_ucc_scrapling.html", "w") as f:
                f.write(content)
            print("  Saved to /tmp/nc_sos_ucc_scrapling.html")
        else:
            print(f"  Unknown content (first 300 chars):")
            print(content[:300])

    except Exception as e:
        print(f"  ERROR: {e}")


async def test_nc_sos_ucc_nodriver():
    """Test nodriver on NC SOS UCC search."""
    print("\n=== NC SOS UCC — nodriver test ===")
    try:
        import nodriver as uc

        url = "https://www.sosnc.gov/online_services/search/by_title/_u_cc"
        print(f"Fetching: {url}")

        browser = await uc.start(
            headless=False,
            browser_args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            sandbox=False,
        )
        page = await browser.get(url)
        await asyncio.sleep(15)

        content = await page.get_content()
        print(f"  Content length: {len(content)}")

        if "just a moment" in content.lower() or "challenge" in content.lower():
            print("  STILL CLOUDFLARE CHALLENGE")
        elif "search" in content.lower() or "ucc" in content.lower():
            print("  SUCCESS — real content!")
            with open("/tmp/nc_sos_ucc_nodriver.html", "w") as f:
                f.write(content)
            print("  Saved to /tmp/nc_sos_ucc_nodriver.html")
        else:
            print(f"  Unknown content (first 300 chars):")
            print(content[:300])

        browser.stop()
    except Exception as e:
        print(f"  ERROR: {e}")


async def test_sc_sos_entity_patchright():
    """Test patchright on SC SOS entity search — reCAPTCHA."""
    print("\n=== SC SOS Entity — patchright test ===")
    try:
        from patchright.async_api import async_playwright

        url = "https://businessfilings.sc.gov/businessfiling"
        print(f"Fetching: {url}")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-gpu"],
            )
            ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await ctx.new_page()
            await page.goto(url, timeout=60000)
            await asyncio.sleep(10)

            content = await page.content()
            print(f"  Content length: {len(content)}")

            # Check for reCAPTCHA
            if "g-recaptcha" in content.lower() or "recaptcha" in content.lower():
                print("  reCAPTCHA found!")

                # Try clicking checkbox
                recaptcha_frame = None
                for frame in page.frames:
                    if "recaptcha/api2/anchor" in frame.url:
                        recaptcha_frame = frame
                        break

                if recaptcha_frame:
                    try:
                        await recaptcha_frame.click(".recaptcha-checkbox-border")
                        print("  Clicked reCAPTCHA checkbox")
                        await asyncio.sleep(5)

                        # Check if auto-solved
                        token = await page.evaluate(
                            "() => document.getElementById('g-recaptcha-response')?.value || ''"
                        )
                        if token:
                            print(f"  AUTO-SOLVED! Token: {token[:60]}...")
                        else:
                            print("  Not auto-solved — visual challenge may appear")
                            # Check for challenge frame
                            for frame in page.frames:
                                if "recaptcha/api2/bframe" in frame.url:
                                    print("  Challenge frame found")
                                    break
                    except Exception as e:
                        print(f"  Checkbox click error: {e}")
                else:
                    print("  No reCAPTCHA anchor frame found")
            elif "search" in content.lower() or "business" in content.lower():
                print("  SUCCESS — search page loaded without CAPTCHA!")
                with open("/tmp/sc_sos_entity_patchright.html", "w") as f:
                    f.write(content)
            else:
                print(f"  Unknown content (first 300 chars):")
                print(content[:300])

            await browser.close()
    except Exception as e:
        print(f"  ERROR: {e}")


async def main():
    await test_nc_sos_ucc_scrapling()
    await asyncio.sleep(5)
    await test_nc_sos_ucc_nodriver()
    await asyncio.sleep(5)
    await test_sc_sos_entity_patchright()
    print("\n=== ALL SOS TESTS COMPLETE ===")


asyncio.run(main())
