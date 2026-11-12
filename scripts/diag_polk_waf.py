#!/usr/bin/env python3
"""
Polk Cloudflare WAF diagnostic — isolates headless-detection vs IP-reputation.

Decision tree (one variable at a time):
  A. headless=True,  direct to search URL     → baseline (expect fail)
  B. headless=False, direct to search URL     → isolate headless-detection
  C. headless=False, warm-up homepage first   → isolate cold-request tell
  D. headless=False, warm-up + human timing   → full human simulation

Each test prints: chars, page type (BLOCKED / CHALLENGE / FORM / RESULTS),
and first 200 chars of visible text.
"""
import asyncio
import sys
import os
import re
import random

sys.path.insert(0, "src")
os.environ["DISPLAY"] = ":99"

from foreclosure_scraper.browser_utils import start_browser

HOMEPAGE = "https://www.polknc.gov/"
SEARCH_URL = "https://cms.revize.com/revize/apps/polkcounty/searchtaxrecord.php"


def classify(content: str) -> str:
    clen = len(content)
    clean = re.sub(r"<[^>]+>", " ", content)
    clean = re.sub(r"\s+", " ", clean).strip()
    low = clean.lower()

    if "sorry, you have been blocked" in low or "blocked" in low and "ray id" in low:
        return f"BLOCKED ({clen} chars): {clean[:200]}"
    if "just a moment" in low:
        return f"CHALLENGE ({clen} chars): {clean[:200]}"
    if "searchtext" in low or "record type" in low:
        return f"FORM ({clen} chars): {clean[:200]}"
    if "taxdetail" in low or "gvhdr" in low:
        return f"RESULTS ({clen} chars): {clean[:200]}"
    return f"UNKNOWN ({clen} chars): {clean[:200]}"


async def test_a_headless_direct():
    """A: headless=True, direct to search URL (baseline)."""
    print("\n=== TEST A: headless=True, direct to search URL ===", flush=True)
    browser = await start_browser(headless=True)
    try:
        page = await browser.get(SEARCH_URL)
        await asyncio.sleep(15)
        content = await page.get_content()
        print(f"  Result: {classify(content)}", flush=True)
    finally:
        try:
            browser.stop()
        except BaseException:
            pass


async def test_b_headful_direct():
    """B: headless=False, direct to search URL (isolate headless-detection)."""
    print("\n=== TEST B: headless=False, direct to search URL ===", flush=True)
    browser = await start_browser(headless=False)
    try:
        page = await browser.get(SEARCH_URL)
        await asyncio.sleep(15)
        content = await page.get_content()
        print(f"  Result: {classify(content)}", flush=True)
    finally:
        try:
            browser.stop()
        except BaseException:
            pass


async def test_c_headful_warmup():
    """C: headless=False, warm-up homepage first, then navigate to search."""
    print("\n=== TEST C: headless=False, warm-up homepage → search ===", flush=True)
    browser = await start_browser(headless=False)
    try:
        # Step 1: Hit homepage, let cookies/session establish
        print("  Step 1: Loading homepage (polknc.gov)...", flush=True)
        page = await browser.get(HOMEPAGE)
        await asyncio.sleep(5)
        hp_content = await page.get_content()
        print(f"  Homepage: {classify(hp_content)}", flush=True)

        # Step 2: Small random delay (human reading time)
        delay = random.uniform(1.5, 3.0)
        print(f"  Step 2: Waiting {delay:.1f}s (human delay)...", flush=True)
        await asyncio.sleep(delay)

        # Step 3: Navigate to search page
        print("  Step 3: Navigating to search page...", flush=True)
        page = await browser.get(SEARCH_URL)
        await asyncio.sleep(15)
        content = await page.get_content()
        print(f"  Result: {classify(content)}", flush=True)
    finally:
        try:
            browser.stop()
        except BaseException:
            pass


async def test_d_headful_warmup_human():
    """D: headless=False, warm-up + human timing (mouse movement, delays)."""
    print("\n=== TEST D: headless=False, warm-up + human timing ===", flush=True)
    browser = await start_browser(headless=False)
    try:
        # Step 1: Hit homepage
        print("  Step 1: Loading homepage...", flush=True)
        page = await browser.get(HOMEPAGE)
        await asyncio.sleep(random.uniform(3, 5))

        # Step 2: Simulate mouse movement on homepage (human behavior)
        print("  Step 2: Simulating mouse movement...", flush=True)
        await page.evaluate("""
        (async () => {
            function move(x, y) {
                window.dispatchEvent(new MouseEvent('mousemove', {clientX: x, clientY: y, bubbles: true}));
            }
            for (let i = 0; i < 8; i++) {
                move(Math.random() * window.innerWidth, Math.random() * window.innerHeight);
                await new Promise(r => setTimeout(r, 100 + Math.random() * 200));
            }
        })()
        """, await_promise=True)
        await asyncio.sleep(random.uniform(1, 2))

        # Step 3: Navigate to search page
        print("  Step 3: Navigating to search page...", flush=True)
        page = await browser.get(SEARCH_URL)

        # Step 4: Wait for page to settle, then check
        await asyncio.sleep(15)
        content = await page.get_content()
        print(f"  Result: {classify(content)}", flush=True)

        # If we got a challenge, wait longer — Cloudflare challenge may auto-resolve
        low = content.lower()
        if "just a moment" in low:
            print("  Challenge detected — waiting 20s for auto-resolve...", flush=True)
            await asyncio.sleep(20)
            content = await page.get_content()
            print(f"  After wait: {classify(content)}", flush=True)

    finally:
        try:
            browser.stop()
        except BaseException:
            pass


async def main():
    print("Polk Cloudflare WAF Diagnostic", flush=True)
    print("=" * 60, flush=True)

    await test_a_headless_direct()
    await asyncio.sleep(3)

    await test_b_headful_direct()
    await asyncio.sleep(3)

    await test_c_headful_warmup()
    await asyncio.sleep(3)

    await test_d_headful_warmup_human()

    print("\n" + "=" * 60, flush=True)
    print("Diagnostic complete.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
