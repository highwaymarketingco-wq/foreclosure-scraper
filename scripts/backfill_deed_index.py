#!/usr/bin/env python3
"""Sweep loss-class deeds into data/deed_index.db, then stamp repeat_tax_loss.

The feed behind Dirty Deeds Tier A #34 (docs/deed_index_scoping_2026-09-20.md):
trustee's, commissioner's and sheriff's deeds for the counties whose Register of
Deeds runs on the CCHS classic-ASP platform (Burke, Cleveland, Henderson,
Lincoln). The sweep fills a sidecar SQLite file; enrich_repeat_tax_loss reads it
and tags board owners who lost a parcel earlier and still hold another.

DRY RUN BY DEFAULT. With no flag this prints the plan and the current sidecar
coverage. It makes no request, opens no board file and writes nothing.

    python scripts/backfill_deed_index.py                    # dry run
    python scripts/backfill_deed_index.py --preview-board    # dry run + read-only board match count
    python scripts/backfill_deed_index.py --sweep-only       # fetch into the sidecar, board untouched
    python scripts/backfill_deed_index.py --apply            # sweep, then join to the board and write it

--preview-board streams the published board with board_stream (constant memory,
read-only). --apply does the same first and stops if no board owner can match, so
the 2.8GB load_board and the write only happen when they can change something.
Run it as the only board process (8GB Mac), and pass --from-year 2026 on later
runs, since the sidecar is upserted and old years are already in it.

POLITENESS. Requests go through the throttled shared client (about one a second
per host). One CCHS host is one wall: the first 403, Cloudflare challenge, CAPTCHA
or login page stops that host for the rest of the run, the other counties on it
are skipped, and the run exits 2. Nothing retries a wall or tries to get past it.
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import deed_index  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_repeat_tax_loss import (  # noqa: E402
    count_candidate_owners, enrich_repeat_tax_loss,
)
from foreclosure_scraper.rod import cchs  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

DEFAULT_COUNTIES = ("Burke", "Cleveland", "Henderson", "Lincoln")
DEFAULT_FROM_YEAR = 2010
AVG_SECONDS_PER_REQUEST = 1.15      # http_client: 0.8s floor plus up to 0.7s jitter, per host


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true",
                      help="sweep, then join to the board and write it (needs the board lock)")
    mode.add_argument("--sweep-only", action="store_true",
                      help="fetch into the sidecar; do not touch the board")
    ap.add_argument("--no-sweep", action="store_true",
                    help="with --apply: skip the fetch and join from the sidecar as it is")
    ap.add_argument("--preview-board", action="store_true",
                    help="read-only: count board owners that match an indexed loser (board_stream)")
    ap.add_argument("--counties", default=",".join(DEFAULT_COUNTIES),
                    help="comma-separated NC county names (CCHS classic-ASP counties only)")
    ap.add_argument("--from-year", type=int, default=DEFAULT_FROM_YEAR)
    ap.add_argument("--to-year", type=int, default=date.today().year)
    ap.add_argument("--db", default=None, help=f"sidecar path (default {deed_index.DB_PATH})")
    ap.add_argument("--docs", default=str(REPO / "docs"), help="board directory")
    return ap.parse_args(argv)


def build_plan(counties, from_year: int, to_year: int) -> list[dict]:
    years = max(0, to_year - from_year + 1)
    out = []
    for county in counties:
        cfg = cchs.CCHS_COUNTIES.get(("NC", county))
        out.append({
            "county": county,
            "host": cfg[0] if cfg else None,
            "years": years,
            # 3 bootstrap pages, then a search and a getall per year window. Windows
            # with no rows skip the getall and windows at the cap split, so this is
            # an estimate, not a bound.
            "est_requests": (3 + 2 * years) if cfg else 0,
        })
    return out


def print_plan(plan: list[dict], from_year: int, to_year: int) -> None:
    print(f"plan: {len(plan)} counties, {from_year}..{to_year}, one search window per year")
    for p in plan:
        if p["host"] is None:
            print(f"  {p['county']:<10} not a CCHS classic-ASP county, will be skipped")
            continue
        mins = p["est_requests"] * AVG_SECONDS_PER_REQUEST / 60
        print(f"  {p['county']:<10} host {p['host']}  ~{p['est_requests']} requests  ~{mins:.1f} min")
    hosts = sorted({p["host"] for p in plan if p["host"]})
    print(f"  hosts touched: {', '.join(hosts) or 'none'} (one wall stops a host and exits 2)")


def print_coverage(db_path) -> None:
    path = Path(db_path) if db_path else deed_index.DB_PATH
    if not path.exists():
        print(f"sidecar {path}: not built yet")
        return
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)     # a dry run must not write
    con.row_factory = sqlite3.Row
    try:
        rows = deed_index.coverage(con)
    finally:
        con.close()
    print(f"sidecar {path}: {sum(r['docs'] for r in rows)} instruments")
    for r in rows:
        print(f"  {r['county']:<10} {r['state']}  {r['docs']} docs, {r['loss_docs']} loss, "
              f"{r['with_losers']} name a loser, {r['min_date']}..{r['max_date']}")


async def sweep_counties(counties, from_year: int, to_year: int, con) -> dict:
    """Sweep each county in turn into the sidecar. A walled host is skipped from
    then on; the result says which counties fetched, which were skipped, and why."""
    start, end = date(from_year, 1, 1), min(date(to_year, 12, 31), date.today())
    summary = {"counties": {}, "walled": {}, "flagged": 0}
    for county in counties:
        cfg = cchs.CCHS_COUNTIES.get(("NC", county))
        if not cfg:
            summary["counties"][county] = {"skipped": "not a CCHS classic-ASP county"}
            continue
        host = cfg[0]
        if host in summary["walled"]:
            summary["counties"][county] = {"skipped": f"host {host} already walled"}
            continue
        res = await cchs.sweep_loss_instruments("NC", county, start, end)
        written = deed_index.upsert(con, res.instruments) if res.instruments else 0
        summary["counties"][county] = {
            "host": host, "requests": res.requests, "windows_with_rows": res.windows,
            "party_rows": res.rows, "instruments": written, "kinds": list(res.kinds),
            "kinds_source": res.kinds_source, "truncated": res.truncated,
            "problems": res.problems, "walled": res.walled,
        }
        if res.walled:
            summary["walled"][host] = res.walled
        if res.walled or res.problems or res.truncated:
            summary["flagged"] += 1
    return summary


def print_sweep(summary: dict) -> None:
    for county, s in summary["counties"].items():
        if "skipped" in s:
            print(f"  {county:<10} skipped: {s['skipped']}")
            continue
        print(f"  {county:<10} {s['instruments']} instruments from {s['party_rows']} party rows, "
              f"{s['requests']} requests, kinds {','.join(s['kinds'])} ({s['kinds_source']})")
        if s["walled"]:
            print(f"    WALL: {s['walled']}. Host stopped, not retried.")
        for w in s["truncated"]:
            print(f"    TRUNCATED window at the row cap: {w}")
        for pr in s["problems"]:
            print(f"    PROBLEM: {pr}")


def preview_board(docs_dir, loss_rows: list[dict]) -> dict:
    """Read-only. Streams the published board (no lazy-detail sidecar, no Listing
    objects) and counts owners that equal an indexed loser."""
    return count_candidate_owners(iter_board_rows(Path(docs_dir) / "listings.json.gz"), loss_rows)


def join_board(docs_dir, loss_rows: list[dict]) -> dict:
    """The only step that loads and writes the board."""
    with board_lock(REPO, owner="backfill_deed_index"):
        rows = load_board(docs_dir)
        before = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("repeat_tax_loss"))
        stats = enrich_repeat_tax_loss(rows, deed_index_rows=loss_rows)
        after = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("repeat_tax_loss"))
        stats.update(board_rows=len(rows), tagged_before=before, tagged_after=after)
        if not stats["tagged_rows"] and not before:
            stats["written"] = False           # nothing changed: do not republish the board
            return stats
        write_artifact(rows, {"backfill_deed_index": stats["tagged_rows"]}, docs_dir=docs_dir)
        stats["written"] = True
        return stats


def main(argv=None) -> int:
    args = parse_args(argv)
    counties = [c.strip() for c in args.counties.split(",") if c.strip()]
    plan = build_plan(counties, args.from_year, args.to_year)
    exit_code = 0

    if not (args.apply or args.sweep_only):
        print("DRY RUN: no request made, no board opened, nothing written.")
        print_plan(plan, args.from_year, args.to_year)
        print_coverage(args.db)
        if args.preview_board:
            rows = deed_index.load_loss_rows(args.db)
            print(f"board preview (read-only stream): {preview_board(args.docs, rows)}")
        print("Re-run with --sweep-only to fetch, or --apply to fetch and join to the board.")
        return 0

    if not args.no_sweep:
        print_plan(plan, args.from_year, args.to_year)
        con = deed_index.connect(args.db)
        try:
            summary = asyncio.run(sweep_counties(counties, args.from_year, args.to_year, con))
            print_sweep(summary)
            if summary["counties"]:
                stats = deed_index.refresh_losers(con)
                print(f"losers refreshed: {stats['rows']} loss rows, {stats['updated']} updated, "
                      f"standing officers dropped: {stats['officers'] or 'none'}")
        finally:
            con.close()
        if summary["flagged"]:
            exit_code = 2                       # a wall, a shape problem or a capped window

    if not args.apply:
        print("sweep only: board not touched.")
        return exit_code

    loss_rows = deed_index.load_loss_rows(args.db)
    print(f"sidecar loss rows naming a loser: {len(loss_rows)}")
    if not loss_rows:
        print("nothing to join: board not touched.")
        return exit_code or 2
    preview = preview_board(args.docs, loss_rows)
    print(f"board preview (read-only stream): {preview}")
    if not preview["candidate_rows"]:
        print("no board owner equals an indexed loser: board not loaded, nothing written.")
        return exit_code
    stats = join_board(args.docs, loss_rows)
    print(f"joined: {stats}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
