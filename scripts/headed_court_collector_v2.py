#!/usr/bin/env python3
"""Headed browser collector for NC eCourts + SC PublicIndex.

Launches a HEADED Chromium browser. The operator solves any CAPTCHA/WAF
challenge manually in the physical browser window. The script then
navigates each search mode, county, and case-type lane, waits for results,
and saves the page HTML.

NC eCourts search modes (all behind the same AWS-WAF):
  - Smart Search (Dashboard/29): case records by county + case type
  - Search Hearings (Dashboard/26): upcoming hearing dates by county + date range

Usage:
    PYTHONPATH=... python scripts/headed_court_collector_v2.py
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

REPO = "/Users/cashhigh/foreclosure-scraper"

NC_COUNTIES = [
    "Buncombe", "Henderson", "Cleveland", "Gaston", "Rutherford",
    "Polk", "Transylvania", "McDowell", "Lincoln", "Mitchell", "Burke",
    "Brunswick", "Pender", "Onslow", "Carteret", "Dare",
]

# Smart Search case categories
NC_SMART_SEARCH_CATEGORIES = [
    "Special Proceeding",
    "Estate",
    "Civil District",
    "Family",
]

# SC counties + lanes
SC_COUNTIES = [
    "Spartanburg", "Anderson", "Pickens", "Oconee", "Cherokee", "Union", "Laurens",
]
SC_LANES = [
    ("G", "CP  ", "420", "foreclosure"),
    ("G", "CP  ", "440", "partition"),
    ("G", "CP  ", "450", "ejectment"),
    ("G", "LP  ", "", "lis_pendens"),
    ("G", "CP  ", "432", "state_tax_lien"),
]


async def wait_for_captcha(page, label="", timeout_s=600):
    """Wait for the user to solve the AWS-WAF CAPTCHA."""
    for attempt in range(timeout_s // 5):
        await asyncio.sleep(5)
        try:
            content = await page.content()
            body_lower = content.lower()
            if "casecriteria" in body_lower or "searchcriteria" in body_lower:
                print(f"  [CAPTCHA SOLVED] {label} ({(attempt+1)*5}s)")
                return True
            if "no cases match" in body_lower:
                print(f"  [PAGE LOADED] {label} ({(attempt+1)*5}s)")
                return True
            # Check if we're on the portal page (not the WAF page)
            if "portal" in body_lower and "confirm you are human" not in body_lower and len(content) > 3000:
                print(f"  [PORTAL LOADED] {label} ({(attempt+1)*5}s)")
                return True
            if attempt % 6 == 0:
                title = await page.title()
                print(f"  [{(attempt+1)*5}s] Waiting for CAPTCHA solve... title: \"{title}\"")
        except Exception as e:
            print(f"  [{(attempt+1)*5}s] Check error: {e}")
    print(f"  [TIMEOUT] {label}")
    return False


async def collect_nc_smart_search(page):
    """Sweep NC eCourts Smart Search (Dashboard/29)."""
    print("\n" + "=" * 60)
    print("NC ECOURTS SMART SEARCH (Dashboard/29)")
    print("=" * 60)

    await page.goto("https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29",
                    wait_until="domcontentloaded", timeout=60000)
    print("  Solve the CAPTCHA in the browser window...")
    if not await wait_for_captcha(page, "Smart Search"):
        print("  Could not get through CAPTCHA. Skipping Smart Search.")
        return 0

    total = 0
    for county in NC_COUNTIES:
        for cat in NC_SMART_SEARCH_CATEGORIES:
            suffix = cat.lower().replace(" ", "_")
            filename = os.path.join(REPO, f"nc_smart_{county.lower()}_{suffix}.html")
            if os.path.exists(filename):
                print(f"  SKIP {county} {cat} (exists)")
                continue

            print(f"  Search: {county} - {cat}...")
            try:
                await page.goto("https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29",
                                wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                # Check for CAPTCHA again
                content = await page.content()
                if "confirm you are human" in content.lower():
                    print(f"    CAPTCHA appeared. Solve it...")
                    if not await wait_for_captcha(page, f"{county} {cat}"):
                        continue

                # Select case category
                await page.evaluate("""(labels) => {
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
                }""", [cat])

                # Set county
                await page.evaluate("""(county) => {
                    const e = document.querySelector('#caseCriteria_SearchCriteria');
                    if (e) {
                        e.value = county;
                        e.dispatchEvent(new Event('input', {bubbles: true}));
                        e.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }""", county)

                # Set date range (6 months back)
                end_date = datetime.now().strftime("%m/%d/%Y")
                start_date = (datetime.now() - timedelta(days=180)).strftime("%m/%d/%Y")
                await page.evaluate("""(dates) => {
                    const inputs = [...document.querySelectorAll('input[type="text"]')];
                    const dateInputs = inputs.filter(i =>
                        (i.id || '').toLowerCase().includes('date') ||
                        (i.name || '').toLowerCase().includes('date')
                    );
                    if (dateInputs.length >= 2) {
                        dateInputs[0].value = dates[0];
                        dateInputs[1].value = dates[1];
                        dateInputs[0].dispatchEvent(new Event('change', {bubbles: true}));
                        dateInputs[1].dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }""", [start_date, end_date])

                # Submit
                submitted = False
                for sel in ['button:has-text("Submit")',
                            'input[type="submit"][value="Submit"]',
                            'button[type="submit"]']:
                    try:
                        await page.click(sel, timeout=4000)
                        submitted = True
                        break
                    except:
                        continue
                if not submitted:
                    try:
                        await page.press('#caseCriteria_SearchCriteria', "Enter")
                        submitted = True
                    except:
                        pass
                if not submitted:
                    print(f"    Could not submit")
                    continue

                await asyncio.sleep(8)

                # Check for CAPTCHA after submit
                content = await page.content()
                if "confirm you are human" in content.lower():
                    print(f"    CAPTCHA after submit. Solve it...")
                    if not await wait_for_captcha(page, f"{county} {cat} post-submit"):
                        continue
                    content = await page.content()

                if "No cases match" in content:
                    print(f"    No cases")
                elif len(content) > 2000:
                    with open(filename, "w") as f:
                        f.write(content)
                    print(f"    SAVED ({len(content)} bytes)")
                    total += 1
                else:
                    print(f"    Too short ({len(content)} bytes)")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"    ERROR: {e}")

    print(f"\n  Smart Search: {total} files saved")
    return total


async def collect_nc_search_hearings(page):
    """Sweep NC eCourts Search Hearings (Dashboard/26)."""
    print("\n" + "=" * 60)
    print("NC ECOURTS SEARCH HEARINGS (Dashboard/26)")
    print("=" * 60)

    await page.goto("https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/26",
                    wait_until="domcontentloaded", timeout=60000)
    print("  Solve the CAPTCHA in the browser window...")
    if not await wait_for_captcha(page, "Search Hearings"):
        print("  Could not get through CAPTCHA. Skipping Search Hearings.")
        return 0

    total = 0
    for county in NC_COUNTIES:
        filename = os.path.join(REPO, f"nc_hearings_{county.lower()}.html")
        if os.path.exists(filename):
            print(f"  SKIP {county} (exists)")
            continue

        print(f"  Hearings: {county}...")
        try:
            await page.goto("https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/26",
                            wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            content = await page.content()
            if "confirm you are human" in content.lower():
                print(f"    CAPTCHA appeared. Solve it...")
                if not await wait_for_captcha(page, f"hearings {county}"):
                    continue

            # Try to set county in the search field
            await page.evaluate("""(county) => {
                const e = document.querySelector('#caseCriteria_SearchCriteria');
                if (e) {
                    e.value = county;
                    e.dispatchEvent(new Event('input', {bubbles: true}));
                    e.dispatchEvent(new Event('change', {bubbles: true}));
                }
            }""", county)

            # Set date range (next 90 days forward looking)
            start_date = datetime.now().strftime("%m/%d/%Y")
            end_date = (datetime.now() + timedelta(days=90)).strftime("%m/%d/%Y")
            await page.evaluate("""(dates) => {
                const inputs = [...document.querySelectorAll('input[type="text"]')];
                const dateInputs = inputs.filter(i =>
                    (i.id || '').toLowerCase().includes('date') ||
                    (i.name || '').toLowerCase().includes('date')
                );
                if (dateInputs.length >= 2) {
                    dateInputs[0].value = dates[0];
                    dateInputs[1].value = dates[1];
                    dateInputs[0].dispatchEvent(new Event('change', {bubbles: true}));
                    dateInputs[1].dispatchEvent(new Event('change', {bubbles: true}));
                }
            }""", [start_date, end_date])

            # Submit
            submitted = False
            for sel in ['button:has-text("Submit")',
                        'input[type="submit"][value="Submit"]',
                        'button[type="submit"]']:
                try:
                    await page.click(sel, timeout=4000)
                    submitted = True
                    break
                except:
                    continue
            if not submitted:
                try:
                    await page.press('#caseCriteria_SearchCriteria', "Enter")
                    submitted = True
                except:
                    pass
            if not submitted:
                print(f"    Could not submit")
                continue

            await asyncio.sleep(8)

            content = await page.content()
            if "confirm you are human" in content.lower():
                print(f"    CAPTCHA after submit. Solve it...")
                if not await wait_for_captcha(page, f"hearings {county} post-submit"):
                    continue
                content = await page.content()

            if "No cases match" in content or "No hearings" in content:
                print(f"    No hearings")
            elif len(content) > 2000:
                with open(filename, "w") as f:
                    f.write(content)
                print(f"    SAVED ({len(content)} bytes)")
                total += 1
            else:
                print(f"    Too short ({len(content)} bytes)")
            await asyncio.sleep(2)
        except Exception as e:
            print(f"    ERROR: {e}")

    print(f"\n  Search Hearings: {total} files saved")
    return total


async def collect_sc_publicindex(page):
    """Sweep SC PublicIndex for each county + case sub-type."""
    print("\n" + "=" * 60)
    print("SC PUBLICINDEX COLLECTION")
    print("=" * 60)

    total = 0
    for county in SC_COUNTIES:
        url = f"https://publicindex.sccourts.org/{county}/PublicIndex/"
        print(f"\n  County: {county}")

        for court_type, case_type, sub_type, suffix in SC_LANES:
            filename = os.path.join(REPO, f"sc_pi_{county.lower()}_{suffix}.html")
            if os.path.exists(filename):
                print(f"    SKIP {county} {suffix} (exists)")
                continue

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(3)

                # Accept disclaimer
                accept = await page.query_selector("#ContentPlaceHolder1_ButtonAccept")
                if accept:
                    try:
                        async with page.expect_navigation(timeout=30000):
                            await accept.click()
                    except:
                        pass
                    await asyncio.sleep(3)

                # Wait for form
                try:
                    await page.wait_for_selector(
                        "#ContentPlaceHolder1_DropDownListCourtType", timeout=20000)
                except:
                    print(f"    No form for {county} {suffix}")
                    continue

                # Court Type
                await page.evaluate(f"""() => {{
                    const el = document.getElementById('ContentPlaceHolder1_DropDownListCourtType');
                    if (el) {{ el.value = {court_type!r}; __doPostBack('ctl00$ContentPlaceHolder1$DropDownListCourtType', ''); }}
                }}""")
                await asyncio.sleep(2)

                # Case Type
                await page.evaluate(f"""() => {{
                    const el = document.getElementById('ContentPlaceHolder1_DropDownListCaseTypes');
                    if (el) {{ el.value = {case_type!r}; __doPostBack('ctl00$ContentPlaceHolder1$DropDownListCaseTypes', ''); }}
                }}""")
                await asyncio.sleep(2)

                # Sub-Type
                if sub_type:
                    sub_type_val = (sub_type + "   ")[:8]
                    await page.evaluate(f"""() => {{
                        const el = document.getElementById('ContentPlaceHolder1_DropdownlistCaseSubType');
                        if (el) {{ el.value = {sub_type_val!r}; __doPostBack('ctl00$ContentPlaceHolder1$DropdownlistCaseSubType', ''); }}
                    }}""")
                    await asyncio.sleep(2)

                # Date filter + range
                today = datetime.now()
                date_to = today.strftime("%m/%d/%Y")
                date_from = (today - timedelta(days=90)).strftime("%m/%d/%Y")
                await page.evaluate(f"""() => {{
                    const d = document.getElementById('ContentPlaceHolder1_DropDownListDateFilter');
                    if (d) d.value = 'Filed';
                    const f = document.getElementById('ContentPlaceHolder1_TextBoxDateFrom');
                    const t = document.getElementById('ContentPlaceHolder1_TextBoxDateTo');
                    if (f) f.value = {date_from!r};
                    if (t) t.value = {date_to!r};
                    const ln = document.getElementById('ContentPlaceHolder1_TextBoxlastName');
                    const fn = document.getElementById('ContentPlaceHolder1_TextBoxFirstname');
                    if (ln) ln.value = '';
                    if (fn) fn.value = '';
                }}""")

                # Submit
                print(f"    Search: {county} - {suffix}...")
                try:
                    async with page.expect_navigation(timeout=60000):
                        await page.evaluate("""() => {
                            const b = document.getElementById('ContentPlaceHolder1_ButtonSearch');
                            if (b) b.click();
                        }""")
                except:
                    pass
                await asyncio.sleep(4)

                content = await page.content()
                if "SearchResults" in content and len(content) > 2000:
                    with open(filename, "w") as f:
                        f.write(content)
                    print(f"    SAVED ({len(content)} bytes)")
                    total += 1
                elif "No Records" in content or "no records" in content.lower():
                    print(f"    No records")
                else:
                    print(f"    No results table ({len(content)} bytes)")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"    ERROR: {e}")

    print(f"\n  SC PublicIndex: {total} files saved")
    return total


async def main():
    print("=" * 60)
    print("HEADED COURT PORTAL COLLECTOR v2")
    print("=" * 60)
    print()
    print("A Chromium window will open. SOLVE CAPTCHAs in that window.")
    print("The script waits for you. It will collect:")
    print("  1. NC Smart Search (16 counties x 4 case types)")
    print("  2. NC Search Hearings (16 counties, forward-looking)")
    print("  3. SC PublicIndex (7 counties x 5 case sub-types)")
    print()

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=300,
            args=["--disable-blink-features=AutomationControlled",
                  "--window-position=0,0", "--window-size=1400,900"],
        )
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/145.0.0.0 Safari/537.36"),
        )
        page = await context.new_page()

        nc_smart = await collect_nc_smart_search(page)
        nc_hearings = await collect_nc_search_hearings(page)
        sc_pi = await collect_sc_publicindex(page)

        print("\n" + "=" * 60)
        print(f"COLLECTION COMPLETE")
        print(f"  NC Smart Search files:  {nc_smart}")
        print(f"  NC Search Hearings:     {nc_hearings}")
        print(f"  SC PublicIndex files:   {sc_pi}")
        print(f"  Total:                  {nc_smart + nc_hearings + sc_pi}")
        print("=" * 60)
        print("Files saved to:", REPO)
        await asyncio.sleep(5)
        await browser.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
