#!/usr/bin/env python3
"""READ-ONLY dry run: how many county-less bankruptcy rows have a petition CourtListener already holds for free?

Feasibility tool for src/foreclosure_scraper/petition_address.py. It

  1. asks CourtListener's public search for dockets whose voluntary petition is already archived
     (available_only=on); nothing is purchased and PACER is never contacted,
  2. matches those docket ids against the published board, read through board_stream.iter_board_rows()
     (constant memory), and
  3. downloads each matching petition from storage.courtlistener.com, lifts the text layer locally,
     and parses the Form 101 "Where you live" block.

It NEVER writes the board, the verification ledgers or docs/. It prints COUNTS ONLY (the repo is public and
debtor names, addresses and case numbers do not belong in a log). `--out` writes the parsed residences to a
local path you choose (keep it outside the repo or under the gitignored data/ tree); it is off by default.

    uv run python scripts/bankruptcy_petition_sweep.py                  # counts only
    uv run python scripts/bankruptcy_petition_sweep.py --out data/bk_petitions.json

Run alone: it streams the whole board once (~300 MB peak, ~20 s) and makes a few dozen polite HTTP calls.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.http_client import client  # noqa: E402
from foreclosure_scraper.petition_address import (  # noqa: E402
    candidate_from_search_hit,
    debtor_name_agrees,
    debtor_name_conflicts,
    parse_petition_pdf,
)
from foreclosure_scraper.scrapers.national.courtlistener_bankruptcy import (  # noqa: E402
    API_BASE,
    COURTS,
    COURT_STATE,
    _auth_headers,
    _load_token,
)

SOURCE = "national.courtlistener_bankruptcy"


async def _enumerate(c, headers, court: str, filed_after: str, max_pages: int) -> list[dict]:
    url = (f"{API_BASE}/search/?type=r&court={court}&filed_after={filed_after}"
           f"&available_only=on&q=%22voluntary+petition%22&page_size=20")
    out: list[dict] = []
    pages = 0
    while url and pages < max_pages:
        r = await c.get(url, headers=headers, timeout=90.0)
        if r.status_code != 200:
            print(f"  {court}: search HTTP {r.status_code}, stopping this court")
            break
        j = r.json()
        for hit in j.get("results", []):
            cand = candidate_from_search_hit(hit, court)
            if cand:
                out.append(cand)
        url = j.get("next")
        pages += 1
    return out


def _board_rows_by_docket(docket_ids: set[int]) -> dict[int, list[dict]]:
    found: dict[int, list[dict]] = collections.defaultdict(list)
    for row in iter_board_rows():
        if row.get("source") != SOURCE:
            continue
        cl = (row.get("raw") or {}).get("courtlistener") or {}
        did = cl.get("docket_id")
        if did in docket_ids:
            found[did].append({
                "county": row.get("county"), "has_street": bool(row.get("street_address")),
                "case_name": cl.get("case_name"), "court": cl.get("court"),
            })
    return found


async def main_async(args) -> int:
    headers = _auth_headers(_load_token())
    stats: collections.Counter = collections.Counter()
    cands: list[dict] = []
    async with client(timeout=90.0) as c:
        for court in COURTS:
            got = await _enumerate(c, headers, court, args.filed_after, args.max_pages)
            print(f"{court}: {len(got)} archived voluntary petitions since {args.filed_after}")
            cands += got
        stats["archived_petitions"] = len(cands)
        by_docket = _board_rows_by_docket({x["docket_id"] for x in cands})
        stats["on_board"] = sum(1 for x in cands if x["docket_id"] in by_docket)
        results: dict[int, dict] = {}
        for cand in cands:
            rows = by_docket.get(cand["docket_id"])
            if not rows:
                continue
            r = await c.get(cand["doc_url"], follow_redirects=True, timeout=90.0)
            if r.status_code != 200:
                stats["download_failed"] += 1
                continue
            parsed = parse_petition_pdf(r.content)
            if not parsed:
                stats["not_form_101_or_unreadable"] += 1
                continue
            stats["form_101_parsed"] += 1
            stats["with_county"] += bool(parsed.get("county"))
            stats["with_street_city_zip"] += bool(parsed.get("street") and parsed.get("city") and parsed.get("zip"))
            court_state = COURT_STATE.get(cand["court"])
            stats["state_differs_from_court"] += bool(parsed.get("state") and parsed["state"] != court_state)
            stats["name_agrees_with_docket"] += bool(
                debtor_name_agrees(rows[0].get("case_name"), parsed.get("debtor_name")))
            stats["name_CONFLICTS_with_docket"] += bool(
                debtor_name_conflicts(rows[0].get("case_name"), parsed.get("debtor_name")))
            for br in rows:
                stats["board_rows_matched"] += 1
                if not br["county"]:
                    stats["board_row_county_less"] += 1
                elif parsed.get("county"):
                    same = br["county"].strip().lower() == parsed["county"].strip().lower()
                    stats["board_county_agrees"] += same
                    stats["board_county_CONTRADICTS_petition"] += (not same)
            results[cand["docket_id"]] = {**parsed, "court": cand["court"], "doc_url": cand["doc_url"]}
    print("\ncounts:")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1))
        print(f"\nwrote {len(results)} parsed residences to {args.out} (private data: do not commit)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--filed-after", default="2026-06-01")
    ap.add_argument("--max-pages", type=int, default=5, help="search pages per court (20 hits each)")
    ap.add_argument("--out", default=None, help="optional local JSON of parsed residences (private data)")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
