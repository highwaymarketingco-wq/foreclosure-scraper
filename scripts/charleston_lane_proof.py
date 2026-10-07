"""Bounded live proof of the Charleston case-type lanes. Counts only, no names.

Runs national.sc_public_index's Charleston path: GET the disclaimer page, POST its
Accept button, then 3 last-name-letter searches, 2 s apart (5 requests). Prints the
results grid's column labels (to confirm the header names the parser reads) and how
many Common Pleas cases fell in each lane, including the 'other' and closed cases
that are counted but no longer emitted as leads ("emitted" = open leads).

NOTE: this accepts the Charleston Public Index disclaimer (the court's Rule 610
terms) on the operator's behalf.

    cd ~/foreclosure-scraper && uv run python scripts/charleston_lane_proof.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from foreclosure_scraper.scrapers.national import sc_public_index as mod  # noqa: E402

mod.SEARCH_PREFIXES = ["B", "M", "W"]


async def main():
    rows = await mod._curl_search_county("charleston")
    st = dict(mod.LAST_CHARLESTON_STATS)
    print(json.dumps({
        "grid_headers": st.get("headers"),
        "cases_seen": st.get("cases"),
        "by_lane": st.get("lanes"),
        "other_not_emitted": st.get("other_not_emitted"),
        "closed_not_emitted": st.get("closed_not_emitted"),
        "party_rows_dropped_eviction_minor_sealed": st.get("dropped_party_rows"),
        "emitted": len(rows),
        "emitted_with_judgment_number": sum(1 for r in rows if r.get("judgment_number")),
        "emitted_filed_2024_plus": sum(1 for r in rows if (r.get("case_number") or "")[:4] >= "2024"),
    }, indent=1))


asyncio.run(main())
