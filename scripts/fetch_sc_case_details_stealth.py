#!/usr/bin/env python3
"""Fetch SC PublicIndex CaseDetails.aspx pages via stealth browser.

The CaseDetails.aspx page is behind the F5/Shape wall, same as PISearch.aspx.
We use the same Scrapling StealthyFetcher that the lis_pendens scraper uses.

Each CaseDetails page contains:
  - Full party information (plaintiff, defendant, attorneys)
  - Case status, disposition, filed date
  - Judgment amount (if entered)
  - Case history / docket entries
  - Sub-type, court type

We process the high-priority cases first (foreclosure + lis pendens).
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")

REPO = "/Users/cashhigh/foreclosure-scraper"
DETAIL_DIR = Path(REPO) / "sc_case_details"
DETAIL_DIR.mkdir(exist_ok=True)

# Load case list
with open("/tmp/sc_case_list.json") as f:
    all_cases = json.load(f)

# Prioritize: foreclosure (420) and lis pendens cases first
# The saved PI files and stealth scraper already have listing_type info
# We'll process all unique case numbers

# Build the URL for each case
def case_url(county, case_number):
    return f"https://publicindex.sccourts.org/{county}/PublicIndex/CaseDetails.aspx?CaseNum={case_number}"


async def fetch_detail(county, case_number):
    """Fetch one CaseDetails page via StealthyFetcher."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return None

    url = case_url(county, case_number)
    try:
        result = await StealthyFetcher.async_fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=60000,
        )
        body = getattr(result, "body", b"")
        if isinstance(body, bytes):
            html = body.decode("utf-8", errors="replace")
        else:
            html = str(body or "")
        return html if len(html) > 1000 else None
    except Exception:
        return None


async def main():
    print(f"Total cases to fetch: {len(all_cases)}")
    print(f"Saving HTML to: {DETAIL_DIR}")
    print()

    # Check which ones we already have
    already = set()
    for f in DETAIL_DIR.glob("*.html"):
        already.add(f.stem)

    todo = []
    for c in all_cases:
        safe = f"{c['county']}_{c['case_number'].replace('/', '_').replace('-', '_')}"
        if safe not in already:
            todo.append(c)

    print(f"Already have: {len(already)}, to fetch: {len(todo)}")

    # Process in batches of 5 (parallel within batch, sequential between batches)
    batch_size = 5
    success = 0
    failed = 0
    total = len(todo)

    for i in range(0, total, batch_size):
        batch = todo[i:i+batch_size]
        tasks = [fetch_detail(c["county"], c["case_number"]) for c in batch]
        pages = await asyncio.gather(*tasks, return_exceptions=True)

        for j, (case, page) in enumerate(zip(batch, pages)):
            if isinstance(page, Exception) or not page:
                failed += 1
                continue

            safe = f"{case['county']}_{case['case_number'].replace('/', '_').replace('-', '_')}"
            path = DETAIL_DIR / f"{safe}.html"
            path.write_text(page, encoding="utf-8", errors="replace")
            success += 1

        batch_num = i // batch_size + 1
        total_batches = (total - 1) // batch_size + 1
        print(f"  Batch {batch_num}/{total_batches}: {success} ok, {failed} failed ({success+failed}/{total})")

        # Brief pause between batches
        await asyncio.sleep(1)

    print(f"\nDone: {success} detail pages saved, {failed} failed")
    print(f"HTML files in: {DETAIL_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
