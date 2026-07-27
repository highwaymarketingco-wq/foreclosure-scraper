#!/usr/bin/env python3
"""SC PublicIndex CaseDetails fetcher using the HKey postback mechanism.

The CaseDetails.aspx page requires a server-generated HKey that is produced
by a POST postback from the search results page. You cannot construct the
URL from the case number alone. This script:

1. Loads the PISearch.aspx page via StealthyFetcher (clears F5/Shape)
2. Fires __doPostBack('SearchResults', 'openDetails$N') for each case
3. Captures the redirect URL containing the HKey
4. Fetches the detail page HTML (parties, judgments, financials, history)

Output: one HTML file per case in sc_case_details/
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")

REPO = Path("/Users/cashhigh/foreclosure-scraper")
DETAIL_DIR = REPO / "sc_case_details"
DETAIL_DIR.mkdir(exist_ok=True)

# Load case list
with open("/tmp/sc_case_list.json") as f:
    all_cases = json.load(f)

COUNTIES = ["Spartanburg", "Anderson", "Pickens", "Oconee", "Cherokee", "Union", "Laurens"]


def _county_url(county: str) -> str:
    return f"https://publicindex.sccourts.org/{county}/PublicIndex/"


async def _fetch_search_page(county: str):
    """Fetch the PISearch.aspx page via StealthyFetcher, accept disclaimer."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return None

    url = _county_url(county)

    async def accept_and_search(page):
        # Wait for disclaimer or form
        try:
            await page.wait_for_selector(
                "#ContentPlaceHolder1_ButtonAccept, #ContentPlaceHolder1_DropDownListCourtType",
                timeout=25000, state="attached",
            )
        except Exception:
            return page

        # Accept disclaimer if present
        accept = await page.evaluate(
            "() => !!document.getElementById('ContentPlaceHolder1_ButtonAccept')"
        )
        if accept:
            try:
                async with page.expect_navigation(timeout=30000):
                    await page.add_script_tag(content=(
                        "(function(){var b=document.getElementById("
                        "'ContentPlaceHolder1_ButtonAccept');if(b)b.click();})();"
                    ))
            except Exception:
                pass
            await asyncio.sleep(3)

        # Wait for search form
        try:
            await page.wait_for_selector("#ContentPlaceHolder1_DropDownListCourtType", timeout=20000)
        except Exception:
            return page

        # Set Court Type = G (Circuit Court)
        await page.add_script_tag(content=(
            "(function(){var el=document.getElementById("
            "'ContentPlaceHolder1_DropDownListCourtType');"
            "if(el){el.value='G';"
            "__doPostBack('ctl00$ContentPlaceHolder1$DropDownListCourtType','');}})();"
        ))
        await asyncio.sleep(2)

        # Set Case Type = CP (Common Pleas)
        await page.add_script_tag(content=(
            "(function(){var el=document.getElementById("
            "'ContentPlaceHolder1_DropDownListCaseTypes');"
            "if(el){el.value='CP  ';"
            "__doPostBack('ctl00$ContentPlaceHolder1$DropDownListCaseTypes','');}})();"
        ))
        await asyncio.sleep(2)

        # Set date filter = Filed, date range = last 180 days
        from datetime import datetime, timedelta
        today = datetime.now()
        date_to = today.strftime("%m/%d/%Y")
        date_from = (today - timedelta(days=180)).strftime("%m/%d/%Y")

        await page.add_script_tag(content=f"""(function(){{
            var d=document.getElementById('ContentPlaceHolder1_DropDownListDateFilter');
            if(d)d.value='Filed';
            var f=document.getElementById('ContentPlaceHolder1_TextBoxDateFrom');
            var t=document.getElementById('ContentPlaceHolder1_TextBoxDateTo');
            if(f)f.value={date_from!r};
            if(t)t.value={date_to!r};
            var ln=document.getElementById('ContentPlaceHolder1_TextBoxlastName');
            var fn=document.getElementById('ContentPlaceHolder1_TextBoxFirstname');
            if(ln)ln.value='';if(fn)fn.value='';
        }})();""")
        await asyncio.sleep(1)

        # Submit search
        try:
            async with page.expect_navigation(timeout=60000):
                await page.add_script_tag(content=(
                    "(function(){var b=document.getElementById("
                    "'ContentPlaceHolder1_ButtonSearch');if(b)b.click();})();"
                ))
        except Exception:
            pass
        await asyncio.sleep(4)

        return page

    try:
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=120000,
            page_action=accept_and_search,
        )
        body = getattr(result, "body", b"")
        html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
        return html if len(html) > 2000 else None
    except Exception:
        return None


async def _extract_case_links_from_search(html: str, county: str):
    """Extract case numbers and result indices from the search results page."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    grid = tree.css_first("table#ContentPlaceHolder1_SearchResults")
    if not grid:
        return []

    cases = []
    seen = set()
    for row in grid.css("tr.standardRow, tr.altRow"):
        cells = row.css("td")
        if len(cells) < 3:
            continue
        anchor = cells[2].css_first("a") if len(cells) > 2 else None
        if not anchor:
            continue
        case_num = anchor.text(strip=True)
        if not case_num or case_num in seen:
            continue
        seen.add(case_num)

        # Extract the result index from the onclick/href
        href = anchor.attributes.get("href") or ""
        onclick = anchor.attributes.get("onclick") or ""
        idx_match = re.search(r"openDetails\$(\d+)", href + onclick)
        idx = int(idx_match.group(1)) if idx_match else None

        # Get title (plaintiff VS defendant)
        title = cells[2].attributes.get("title") or ""

        cases.append({
            "case_number": case_num,
            "county": county,
            "result_index": idx,
            "title": title,
        })

    return cases


async def _fetch_case_details_via_postback(page, county: str, case_index: int):
    """Fire the openDetails postback and capture the redirect URL with HKey."""
    try:
        # Execute the postback via JavaScript
        redirect_url = await page.evaluate(f"""() => {{
            return new Promise((resolve) => {{
                var form = document.forms[0];
                var formData = new FormData(form);
                formData.set('__EVENTTARGET', 'ctl00$ContentPlaceHolder1$SearchResults');
                formData.set('__EVENTARGUMENT', 'openDetails${case_index}');
                fetch(window.location.href, {{
                    method: 'POST',
                    body: formData,
                    redirect: 'follow',
                    credentials: 'same-origin',
                }}).then(r => resolve(r.url)).catch(e => resolve('ERROR:' + e.message));
            }});
        }}""")
        return redirect_url
    except Exception:
        return None


async def main():
    print(f"=== SC CASE DETAIL FETCHER (HKey) ===")
    print(f"Total cases to process: {len(all_cases)}")
    print(f"Output directory: {DETAIL_DIR}")
    print()

    # Process per county
    by_county = {}
    for c in all_cases:
        county = c.get("county", "?")
        by_county.setdefault(county, []).append(c)

    total_saved = 0
    total_failed = 0

    for county in COUNTIES:
        cases = by_county.get(county, [])
        if not cases:
            print(f"\n{county}: no cases to process")
            continue

        print(f"\n{county}: {len(cases)} cases")

        # Check which we already have
        already = 0
        todo = []
        for c in cases:
            safe = f"{county}_{c['case_number'].replace('/', '_').replace('-', '_')}"
            if (DETAIL_DIR / f"{safe}.html").exists():
                already += 1
            else:
                todo.append(c)

        if already:
            print(f"  Already have: {already}")
        if not todo:
            print(f"  Nothing to do")
            continue

        print(f"  To fetch: {len(todo)}")

        # Fetch the search results page via stealth
        print(f"  Loading search page via stealth...")
        html = await _fetch_search_page(county)
        if not html:
            print(f"  FAILED to load search page")
            total_failed += len(todo)
            continue

        # Extract case links from the results
        found_cases = await _extract_case_links_from_search(html, county)
        print(f"  Found {len(found_cases)} cases in search results")

        # Now we need to use the page context to fire postbacks
        # The stealth fetcher already closed, so we need a different approach
        # Use the raw HTML to extract __VIEWSTATE and __EVENTVALIDATION
        # then fire POST requests with curl_cffi

        from foreclosure_scraper.http_client import client

        viewstate_match = re.search(r'name="__VIEWSTATE"\s+id="__VIEWSTATE"\s+value="([^"]*)"', html)
        eventval_match = re.search(r'name="__EVENTVALIDATION"\s+id="__EVENTVALIDATION"\s+value="([^"]*)"', html)
        viewstate = viewstate_match.group(1) if viewstate_match else ""
        eventval = eventval_match.group(1) if eventval_match else ""

        if not viewstate:
            print(f"  No __VIEWSTATE found in search page")
            total_failed += len(todo)
            continue

        search_url = f"https://publicindex.sccourts.org/{county}/PublicIndex/PISearch.aspx"

        async with client(timeout=30.0) as c:
            for i, case in enumerate(todo):
                case_num = case["case_number"]
                idx = case.get("result_index")

                # Try to find the index from the found_cases list
                if idx is None:
                    for fc in found_cases:
                        if fc["case_number"] == case_num:
                            idx = fc["result_index"]
                            break

                if idx is None:
                    # Try a direct CaseDetails URL without HKey (sometimes works)
                    detail_url = f"https://publicindex.sccourts.org/{county}/PublicIndex/CaseDetails.aspx?CaseNum={case_num}"
                else:
                    # Fire the postback to get the HKey URL
                    post_data = {
                        "__EVENTTARGET": "ctl00$ContentPlaceHolder1$SearchResults",
                        "__EVENTARGUMENT": f"openDetails${idx}",
                        "__VIEWSTATE": viewstate,
                        "__EVENTVALIDATION": eventval,
                    }
                    try:
                        r = await c.post(search_url, data=post_data, follow_redirects=True)
                        detail_url = str(r.url)
                        if "CaseDetails" not in detail_url:
                            # Didn't get redirected to detail page
                            total_failed += 1
                            continue
                    except Exception:
                        total_failed += 1
                        continue

                # Fetch the detail page
                try:
                    r = await c.get(detail_url)
                    if r.status_code == 200 and len(r.text) > 1000:
                        safe = f"{county}_{case_num.replace('/', '_').replace('-', '_')}"
                        path = DETAIL_DIR / f"{safe}.html"
                        path.write_text(r.text, encoding="utf-8", errors="replace")
                        total_saved += 1
                        if total_saved % 10 == 0:
                            print(f"  Saved {total_saved} detail pages...")
                    else:
                        total_failed += 1
                except Exception:
                    total_failed += 1

                await asyncio.sleep(0.5)

        print(f"  {county}: saved {total_saved} total, {total_failed} failed")

    print(f"\n=== DONE ===")
    print(f"Total detail pages saved: {total_saved}")
    print(f"Total failed: {total_failed}")
    print(f"HTML files in: {DETAIL_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
