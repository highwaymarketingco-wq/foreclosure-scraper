"""Bounded live proof of the Charleston Public Index reader. Counts and labels only, no names.

Default: the date-window search for the last 60 days, about 20 requests: GET the disclaimer
page, POST its Accept button, the court and case-type postbacks, then 'Case Filed' windows of
30 days for each lead subtype (foreclosure, partition, quiet title, lis pendens, judgments),
a window that fills the grid split in half. Prints the query shape (labels only), a trace of
every request (HTTP status, grid rows, cap, the page's own message), and the cases seen and
kept per lane. State goes to a temporary file, never to data/.

--letters: also the letter sweep (B, M, W; 5 more requests) with the per-lane profile of
distinct status / type / subtype values and filed / disposition years.

Every request 3 s apart, one at a time. NOTE: this accepts the Charleston Public Index
disclaimer (the court's Rule 610 terms) on the operator's behalf.

    cd ~/foreclosure-scraper && uv run python scripts/charleston_lane_proof.py [--letters]
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


def _kept_share(st, lane):
    return f"{(st.get('emitted_by_lane') or {}).get(lane, 0)}/{(st.get('lanes') or {}).get(lane, 0)}"


async def main():
    if "--letters" in sys.argv:
        os.environ["CHARLESTON_PI_DATE_WINDOW"] = "0"
        mod.SEARCH_PREFIXES = ["B", "M", "W"]
        rows = await mod._curl_search_county("charleston")
        st = dict(mod.LAST_CHARLESTON_STATS)
        print(json.dumps({
            "part": "letters B, M, W",
            "grid_headers": st.get("headers"),
            "cases_seen": st.get("cases"), "by_lane": st.get("lanes"),
            "kept_by_lane": st.get("emitted_by_lane"),
            "foreclosure_kept_share": _kept_share(st, "foreclosure"),
            "foreclosure_judgment_entered": st.get("foreclosure_judgment_entered"),
            "emitted": len(rows),
            "profile_per_lane": {lane: {f: _top(c) for f, c in v.items()}
                                 for lane, v in (st.get("profile") or {}).items()},
        }, indent=1))

    os.environ["CHARLESTON_PI_DATE_WINDOW"] = "1"
    mod.SEARCH_PREFIXES = []
    mod.FILED_LOOKBACK_DAYS = 59          # 60 days including today
    mod.WINDOW_DAYS = 30
    mod.DISPOSED_SWEEP = False            # no disposition sweep in this proof
    mod.WINDOW_MAX_REQUESTS = int(os.environ.get("PROOF_MAX_REQUESTS", "18"))
    mod.CHARLESTON_STATE_FILE = Path(tempfile.mkdtemp()) / "state.json"
    rows = await mod._curl_search_county("charleston")
    st = dict(mod.LAST_CHARLESTON_STATS)
    search = st.get("search") or {}
    print(json.dumps({
        "part": "Case Filed date windows, last 60 days, per lead subtype",
        "search_form": st.get("form"),
        "query_shape": {"court": "Circuit Court", "case_type": "Common Pleas",
                        "date_type": (st.get("form") or {}).get("date_used", {}).get("filed"),
                        "subtypes": search.get("subtypes"), "last_name": "blank" if search.get("mode") == "date_window"
                        else "one letter per request", "window_days": mod.WINDOW_DAYS},
        "mode": search.get("mode"), "fallback": search.get("fallback"),
        "requests": search.get("requests"), "windows": search.get("windows"),
        "split": search.get("split"), "capped_days": search.get("capped_days"),
        "budget_exhausted": search.get("budget_exhausted"),
        "trace": search.get("trace"),
        "cases_seen": st.get("cases"), "by_lane": st.get("lanes"),
        "kept_by_lane": st.get("emitted_by_lane"),
        "foreclosure_kept_share": _kept_share(st, "foreclosure"),
        "filed_years": {lane: v.get("filed_year") for lane, v in (st.get("profile") or {}).items()},
        "status_per_lane": {lane: _top(v.get("status") or {}) for lane, v in (st.get("profile") or {}).items()},
        "emitted": len(rows),
    }, indent=1))


asyncio.run(main())
