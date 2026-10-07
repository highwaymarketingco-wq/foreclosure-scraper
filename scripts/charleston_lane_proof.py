"""Bounded live proof of the Charleston Public Index reader. Counts and labels only, no names.

Part 1, letter sweep (5 requests): GET the disclaimer page, POST its Accept button, then
3 last-name-letter searches. Prints, per lane, the DISTINCT case status / type / subtype
values with counts, the filed and disposition year distributions, and how many cases the
per-lane lead rules keep (foreclosure: open, or judgment entered in the last 9 months).

Part 2, filed-date window (about 6 requests): a fresh session, the search form's own date
controls (printed), Circuit / Common Pleas, two 14-day windows ending today. Writes its state
to a temporary file, never to data/.

Every request 3 s apart, one at a time. NOTE: this accepts the Charleston Public Index
disclaimer (the court's Rule 610 terms) on the operator's behalf.

    cd ~/foreclosure-scraper && uv run python scripts/charleston_lane_proof.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from foreclosure_scraper.scrapers.national import sc_public_index as mod  # noqa: E402

mod.REQUEST_DELAY = 3.0
mod.WINDOW_DELAY = 3.0


def _top(d, n=25):
    return dict(sorted(d.items(), key=lambda kv: -kv[1])[:n])


async def main():
    # Part 1: letter sweep (date window off)
    os.environ["CHARLESTON_PI_DATE_WINDOW"] = "0"
    mod.SEARCH_PREFIXES = ["B", "M", "W"]
    rows = await mod._curl_search_county("charleston")
    st = dict(mod.LAST_CHARLESTON_STATS)
    profile = {lane: {f: _top(c) for f, c in v.items()} for lane, v in (st.get("profile") or {}).items()}
    fc_seen = (st.get("lanes") or {}).get("foreclosure", 0)
    fc_kept = (st.get("emitted_by_lane") or {}).get("foreclosure", 0)
    print(json.dumps({
        "part": "letters B, M, W",
        "grid_headers": st.get("headers"),
        "search_form": st.get("form"),
        "cases_seen": st.get("cases"),
        "by_lane": st.get("lanes"),
        "kept_by_lane": st.get("emitted_by_lane"),
        "not_lead_by_lane": st.get("not_lead_by_lane"),
        "foreclosure_kept_share": f"{fc_kept}/{fc_seen}",
        "foreclosure_judgment_entered": st.get("foreclosure_judgment_entered"),
        "party_rows_dropped_eviction_minor_sealed": st.get("dropped_party_rows"),
        "emitted": len(rows),
        "profile_per_lane": profile,
    }, indent=1))

    # Part 2: filed-date window, bounded, temporary state
    os.environ["CHARLESTON_PI_DATE_WINDOW"] = "1"
    mod.SEARCH_PREFIXES = []
    mod.FILED_LOOKBACK_DAYS = 27
    mod.WINDOW_MAX_REQUESTS = 4
    mod.CHARLESTON_STATE_FILE = Path(tempfile.mkdtemp()) / "state.json"
    rows = await mod._curl_search_county("charleston")
    st = dict(mod.LAST_CHARLESTON_STATS)
    print(json.dumps({
        "part": "filed-date window (2 x 14 days, max 4 requests after the disclaimer)",
        "search_form": st.get("form"),
        "search": st.get("search"),
        "cases_seen": st.get("cases"),
        "by_lane": st.get("lanes"),
        "kept_by_lane": st.get("emitted_by_lane"),
        "filed_years": {lane: v.get("filed_year") for lane, v in (st.get("profile") or {}).items()},
        "emitted": len(rows),
    }, indent=1))


asyncio.run(main())
