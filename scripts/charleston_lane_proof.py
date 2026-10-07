"""Bounded live proof of the Charleston case-type lanes. Counts only, no names.

Runs national.sc_public_index's Charleston path (GET the disclaimer page, POST its
Accept button, then 3 last-name-letter searches, 2 s apart: 5 requests) and prints
how many Common Pleas cases fell in each lane. NOTE: this accepts the Charleston
Public Index disclaimer (the court's Rule 610 terms) on the operator's behalf.

    cd ~/foreclosure-scraper && uv run python scripts/charleston_lane_proof.py
"""
import asyncio
import collections
import json
import sys

sys.path.insert(0, "/Users/cashhigh/foreclosure-scraper/src")
from foreclosure_scraper.scrapers.national import sc_public_index as mod  # noqa: E402

mod.SEARCH_PREFIXES = ["B", "M", "W"]


async def main():
    rows = await mod._curl_search_county("charleston")
    lanes = collections.Counter((r.get("lane") or "(no subtype column)") for r in rows)
    years = collections.Counter((r.get("case_number") or "")[:4] for r in rows)
    print(json.dumps({
        "cases": len(rows),
        "header_aware": any("lane" in r for r in rows),
        "by_lane": lanes.most_common(),
        "with_judgment_number": sum(1 for r in rows if r.get("judgment_number")),
        "filed_2024_plus": sum(n for y, n in years.items() if y >= "2024"),
    }, indent=1))


asyncio.run(main())
