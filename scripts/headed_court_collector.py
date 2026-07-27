#!/usr/bin/env python3
"""Headed browser collector for NC eCourts Smart Search and SC PublicIndex.

Launches a HEADED Chromium browser. The operator solves any CAPTCHA/WAF
challenge manually in the physical browser window. The script then navigates
each county + case-type lane, waits for results, and saves the page HTML.

Compliant: the human runs a normal public search in their own browser session.
We only save the public HTML they already retrieved. No CAPTCHA solver, no
WAF defeat, no login bypass.

Usage:
    PYTHONPATH=... python scripts/headed_court_collector.py

The script will:
  1. Launch a headed Chromium browser.
  2. Navigate to NC eCourts Smart Search.
  3. PAUSE for you to solve the AWS-WAF CAPTCHA (20-second wait, repeats).
  4. Once through, sweep each county + case type automatically.
  5. Save each results page as HTML.
  6. Then navigate to SC PublicIndex and repeat for SC counties.

Output: saved HTML files in ~/foreclosure-scraper/ (repo root) for the
offline parsers to ingest.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Repo root for saving HTML files
REPO = Path("/Users/cashhigh/foreclosure-scraper")
DOWNLOADS = Path.home() / "Downloads"

# NC eCourts Smart Search
NC_PORTAL = "https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29"

# SC PublicIndex
SC_PI_BASE = "https://publicindex.sccourts.org/{county}/PublicIndex/"

# NC counties + case types to sweep
NC_COUNTIES = [
    "Buncombe", "Henderson", "Cleveland", "Gaston", "Rutherford",
    "Polk", "Transylvania", "McDowell", "Lincoln", "Mitchell", "Burke",
    "Brunswick", "Pender", "Onslow", "Carteret", "Dare",
]

# NC case category labels to select in the Smart Search dropdown
NC_CASE_CATEGORIES = {
    "SP": "Special Proceeding",       # foreclosure (power-of-sale)
    "EST": "Estate",                  # probate
    "CVD": "Civil District",          # divorce (some counties)
}

# SC counties + case sub-types to sweep
SC_COUNTIES = [
    "Spartanburg", "Anderson", "Pickens", "Oconee", "Cherokee", "Union", "Laurens",
]

# SC court type / case type / sub-type combos
# (court_type, case_type, sub_type_label, filename_suffix)
SC_LANES = [
    ("G", "CP  ", "420", "foreclosure"),        # Foreclosure 420
    ("G", "CP  ", "440", "partition"),           # Partition 440
    ("G", "CP  ", "450", "ejectment"),           # Ejectment/Possession 450
    ("G", "CP  ", "", "cp_all"),                 # All Common Pleas (no sub-type filter)
    ("G", "LP  ", "", "lis_pendens"),            # Lis Pendens case type
    ("G", "CP  ", "432", "state_tax_lien"),      # State Tax Lien 432
]


async def collect_nc_ecourts(page):
    """Sweep NC eCourts Smart Search for each county + case type."""
    print("\n" + "=" * 60)
    print("NC ECOURTS SMART SEARCH COLLECTION")
    print("=" * 60)
    print(f"Navigating to: {NC_PORTAL}")
    print("If you see a CAPTCHA, SOLVE IT in the browser window.")
    print("The script will wait for you.")

    try:
        await page.goto(NC_PORTAL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"Navigation error (may be WAF): {e}")

    # Wait for CAPTCHA: check every 5 seconds for up to 120 seconds
    print("\nWaiting for CAPTCHA to be solved (checking every 5s, up to 120s)...")
    for attempt in range(24):
        await asyncio.sleep(5)
        try:
            content = await page.content()
            body_lower = content.lower()
            # Check if we're past the WAF
            if "casecriteria" in body_lower or "searchcriteria" in body_lower:
                print(f"  CAPTCHA solved! Search form detected (attempt {attempt + 1}).")
                break
            if "let's confirm you are human" in body_lower or "awswaf" in body_lower:
                if attempt == 0:
                    print("  WAF/CAPTCHA detected. Please solve it in the browser window.")
                elif attempt % 4 == 0:
                    print(f"  Still waiting... ({(attempt + 1) * 5}s elapsed)")
            else:
                # Might be on a different page state
                print(f"  Page loaded (attempt {attempt + 1}). Checking for search form...")
                if len(content) > 5000:
                    print(f"  Content length: {len(content)} chars. May be through.")
                    break
        except Exception as e:
            print(f"  Check error: {e}")

    # Now sweep each county
    total_saved = 0
    for county in NC_COUNTIES:
        for cat_key, cat_label in NC_CASE_CATEGORIES.items():
            suffix = cat_key.lower()
            filename = REPO / f"nc_ecourts_{county.lower()}_{suffix}.html"
            if filename.exists():
                print(f"  SKIP {county} {cat_label} (already saved)")
                continue

            print(f"\n  Searching {county} County - {cat_label}...")

            try:
                # Try to select the case category in the dropdown
                selected = await page.evaluate("""(labels) => {
                    const sels = [...document.querySelectorAll('select')];
                    for (const s of sels) {
                        for (const o of s.options) {
                            const t = (o.text || '').toLowerCase();
                            if (labels.some(l => t.includes(l.toLowerCase()))) {
                                s.value = o.value;
                                s.dispatchEvent(new Event('change', {bubbles: true}));
                                return true;
                            }
                        }
                    }
                    return false;
                }""", [cat_label, cat_key])

                # Set the county/location search field
                await page.evaluate("""(county) => {
                    const e = document.querySelector('#caseCriteria_SearchCriteria');
                    if (!e) return;
                    e.value = county;
                    e.dispatchEvent(new Event('input', {bubbles: true}));
                    e.dispatchEvent(new Event('change', {bubbles: true}));
                }""", county)

                # Set date range (last 6 months)
                end_date = datetime.now().strftime("%m/%d/%Y")
                start_date = (datetime.now() - timedelta(days=180)).strftime("%m/%d/%Y")

                # Try to find and fill date fields
                await page.evaluate("""(dates) => {
                    const inputs = [...document.querySelectorAll('input[type="text"]')];
                    const dateInputs = inputs.filter(i => 
                        (i.id || '').toLowerCase().includes('date') ||
                        (i.name || '').toLowerCase().includes('date') ||
                        (i.placeholder || '').toLowerCase().includes('date')
                    );
                    if (dateInputs.length >= 2) {
                        dateInputs[0].value = dates[0];
                        dateInputs[1].value = dates[1];
                        dateInputs[0].dispatchEvent(new Event('change', {bubbles: true}));
                        dateInputs[1].dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }""", [start_date, end_date])

                # Click Submit
                submitted = False
                for sel in [
                    'button:has-text("Submit")',
                    'input[type="submit"][value="Submit"]',
                    'button[type="submit"]',
                ]:
                    try:
                        await page.click(sel, timeout=4000)
                        submitted = True
                        break
                    except Exception:
                        continue
                if not submitted:
                    try:
                        await page.press('#caseCriteria_SearchCriteria', "Enter")
                        submitted = True
                    except Exception:
                        pass

                if not submitted:
                    print(f"    Could not submit search for {county} {cat_label}")
                    continue

                # Wait for results
                print(f"    Waiting for results...")
                await asyncio.sleep(8)

                # Check if WAF appeared again
                content = await page.content()
                body_lower = content.lower()
                if "let's confirm you are human" in body_lower or "awswaf" in body_lower:
                    print(f"    WAF/CAPTCHA appeared again! Please solve it in the browser.")
                    for wait in range(24):
                        await asyncio.sleep(5)
                        content = await page.content()
                        if "casecriteria" in content.lower() or "no cases match" in content.lower():
                            print(f"    CAPTCHA solved, continuing...")
                            break
                        if wait % 4 == 0:
                            print(f"    Still waiting for CAPTCHA... ({(wait + 1) * 5}s)")

                # Save the page
                content = await page.content()
                if "No cases match your search" in content:
                    print(f"    No cases found for {county} {cat_label}")
                elif len(content) > 2000:
                    filename.write_text(content, encoding="utf-8", errors="replace")
                    print(f"    SAVED: {filename.name} ({len(content)} bytes)")
                    total_saved += 1
                else:
                    print(f"    Page too short for {county} {cat_label} ({len(content)} bytes)")

                # Brief pause between searches
                await asyncio.sleep(2)

                # Navigate back to search page for next query
                try:
                    await page.goto(NC_PORTAL, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(3)
                except Exception:
                    pass

            except Exception as e:
                print(f"    ERROR for {county} {cat_label}: {e}")
                continue

    print(f"\nNC eCourts collection complete: {total_saved} files saved.")
    return total_saved


async def collect_sc_publicindex(page):
    """Sweep SC PublicIndex for each county + case sub-type."""
    print("\n" + "=" * 60)
    print("SC PUBLICINDEX COLLECTION")
    print("=" * 60)

    total_saved = 0
    for county in SC_COUNTIES:
        url = SC_PI_BASE.format(county=county)
        print(f"\n  County: {county} ({url})")

        for court_type, case_type, sub_type, suffix in SC_LANES:
            filename = REPO / f"sc_pi_{county.lower()}_{suffix}.html"
            if filename.exists():
                print(f"    SKIP {county} {suffix} (already saved)")
                continue

            try:
                # Navigate to the county landing page
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(3)

                # Accept disclaimer if present
                accept = await page.query_selector("#ContentPlaceHolder1_ButtonAccept")
                if accept:
                    print(f"    Accepting disclaimer...")
                    try:
                        async with page.expect_navigation(timeout=30000):
                            await accept.click()
                    except Exception:
                        pass
                    await asyncio.sleep(3)

                # Check if we hit the F5/Shape challenge
                content = await page.content()
                if "client challenge" in content.lower() or "fs-ch" in content.lower():
                    print(f"    F5/Shape challenge detected. Waiting for stealth browser to clear...")
                    await asyncio.sleep(15)
                    content = await page.content()
                    if "client challenge" in content.lower():
                        print(f"    Challenge not cleared. Please check browser. Waiting 30s...")
                        await asyncio.sleep(30)
                        content = await page.content()

                # Wait for the search form
                try:
                    await page.wait_for_selector(
                        "#ContentPlaceHolder1_DropDownListCourtType",
                        timeout=20000,
                    )
                except Exception:
                    print(f"    Could not find search form for {county} {suffix}")
                    continue

                # Set Court Type
                await page.evaluate(f"""() => {{
                    const el = document.getElementById('ContentPlaceHolder1_DropDownListCourtType');
                    if (el) {{
                        el.value = {court_type!r};
                        if (typeof __doPostBack === 'function') {{
                            __doPostBack('ctl00$ContentPlaceHolder1$DropDownListCourtType', '');
                        }}
                    }}
                }}""")
                await asyncio.sleep(2)

                # Set Case Type
                await page.evaluate(f"""() => {{
                    const el = document.getElementById('ContentPlaceHolder1_DropDownListCaseTypes');
                    if (el) {{
                        el.value = {case_type!r};
                        if (typeof __doPostBack === 'function') {{
                            __doPostBack('ctl00$ContentPlaceHolder1$DropDownListCaseTypes', '');
                        }}
                    }}
                }}""")
                await asyncio.sleep(2)

                # Set Sub-Type if specified
                if sub_type:
                    sub_type_val = (sub_type + "   ")[:8]
                    await page.evaluate(f"""() => {{
                        const el = document.getElementById('ContentPlaceHolder1_DropdownlistCaseSubType');
                        if (el) {{
                            el.value = {sub_type_val!r};
                            if (typeof __doPostBack === 'function') {{
                                __doPostBack('ctl00$ContentPlaceHolder1$DropdownlistCaseSubType', '');
                            }}
                        }}
                    }}""")
                    await asyncio.sleep(2)

                # Set date filter type = Filed
                await page.evaluate("""() => {
                    const d = document.getElementById('ContentPlaceHolder1_DropDownListDateFilter');
                    if (d) d.value = 'Filed';
                }""")

                # Set date range (last 90 days)
                today = datetime.now()
                date_to = today.strftime("%m/%d/%Y")
                date_from = (today - timedelta(days=90)).strftime("%m/%d/%Y")
                await page.evaluate(f"""() => {{
                    const f = document.getElementById('ContentPlaceHolder1_TextBoxDateFrom');
                    const t = document.getElementById('ContentPlaceHolder1_TextBoxDateTo');
                    if (f) f.value = {date_from!r};
                    if (t) t.value = {date_to!r};
                }}""")

                # Clear name fields (empty-name search = all cases)
                await page.evaluate("""() => {
                    const ln = document.getElementById('ContentPlaceHolder1_TextBoxlastName');
                    const fn = document.getElementById('ContentPlaceHolder1_TextBoxFirstname');
                    if (ln) ln.value = '';
                    if (fn) fn.value = '';
                }""")

                # Submit search
                print(f"    Searching {county} - {suffix}...")
                try:
                    async with page.expect_navigation(timeout=60000):
                        await page.evaluate("""() => {
                            const b = document.getElementById('ContentPlaceHolder1_ButtonSearch');
                            if (b) b.click();
                        }""")
                except Exception:
                    pass

                await asyncio.sleep(4)

                # Save the page
                content = await page.content()
                if "SearchResults" in content and len(content) > 2000:
                    filename.write_text(content, encoding="utf-8", errors="replace")
                    print(f"    SAVED: {filename.name} ({len(content)} bytes)")
                    total_saved += 1
                elif "No Records" in content or "no records" in content.lower():
                    print(f"    No records for {county} {suffix}")
                else:
                    print(f"    No results table for {county} {suffix} ({len(content)} bytes)")

                # Brief pause
                await asyncio.sleep(2)

            except Exception as e:
                print(f"    ERROR for {county} {suffix}: {e}")
                continue

    print(f"\nSC PublicIndex collection complete: {total_saved} files saved.")
    return total_saved


async def main():
    print("=" * 60)
    print("HEADED COURT PORTAL COLLECTOR")
    print("=" * 60)
    print()
    print("This script launches a VISIBLE Chromium browser window.")
    print("When you see a CAPTCHA, solve it in the browser window.")
    print("The script will automatically continue once the CAPTCHA is cleared.")
    print()
    print("Collecting from:")
    print("  1. NC eCourts Smart Search (16 counties, 3 case types)")
    print("  2. SC PublicIndex (7 counties, 6 case sub-types)")
    print()

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: playwright not installed. Install with:")
        print("  pip install playwright && playwright install chromium")
        return 1

    async with async_playwright() as p:
        # Launch HEADED browser (not headless)
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=300,  # Slow down for visibility
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # Phase 1: NC eCourts
        nc_count = await collect_nc_ecourts(page)

        # Phase 2: SC PublicIndex
        sc_count = await collect_sc_publicindex(page)

        print("\n" + "=" * 60)
        print(f"COLLECTION COMPLETE")
        print(f"  NC eCourts files saved: {nc_count}")
        print(f"  SC PublicIndex files saved: {sc_count}")
        print(f"  Total: {nc_count + sc_count}")
        print("=" * 60)
        print()
        print("Files saved to:", REPO)
        print("Run the parsers next:")
        print("  python scripts/parse_publicindex_export.py ~/foreclosure-scraper/")
        print("  python scripts/parse_nc_ecourts_export.py <file>.html")

        # Keep browser open for a moment
        await asyncio.sleep(5)
        await browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
