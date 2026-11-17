#!/usr/bin/env python3
"""One-off ingest: land the 8 jail_booking ROSTERS entries wired round 12/13
but never run against the real board.

WHY THIS EXISTS
    Round 12 (commit 50cda501, 2026-11-17 09:31) wired 7 Citizen Connect
    counties into scrapers/national/jail_bookings.py's ROSTERS list: Scotland
    NC, Dorchester SC, Sampson NC, Surry NC, Edgecombe NC, Greene NC, Yancey
    NC. Round 13 (commit 6221208f, 10:39) wired an 8th, Alexander NC, via
    p2c_centralsquare. Both commits said "gap_matrix confirms... now
    built-but-low-yield" -- the exact wired-but-never-run shape round 16's
    brief named as this session's single highest-leverage recurring finding
    (the same shape SC Lancaster code_enforcement was in before
    scripts/backfill_lancaster_code_enforcement.py). Neither commit touched
    any board data file (confirmed: `git show --stat` on both lists only
    enrichment_jail_bookings.py + jail_bookings.py).

    Scoping this round 16 catch-up to just these 8 ALSO caught a real second
    bug while preparing it: _to_listing(rec, state, county)'s source_url
    builder is a hardcoded (state, county) elif chain with no fallback that
    reads the ROSTERS target string, and neither round 12 nor round 13 added
    a branch for its own new counties -- every one of these 8 counties'
    bookings would otherwise have landed with source_url="" (not a dedupe
    bug, since _booking_identity() already keys dedupe_key() off a real or
    synthesized per-booking id rather than source_url -- just a missing
    "view source" link on the lead card). Fixed in the same commit as this
    script, with its own explanation inline at the new elif branches.

WHY A SCOPED SCRIPT, NOT THE FULL national.jail_bookings SCRAPER
    JailBookingsScraper.fetch() iterates ALL ~60 ROSTERS entries concurrently
    -- correct for a real scheduled run, unnecessary network load for a
    one-time catch-up on 8 new rows. This calls the module's own
    `_fetch_roster(state, county, vendor, target)` directly for just these 8
    tuples (the same dispatch function the full scraper uses per-roster-row,
    zero parallel logic), then `_to_listing()`, then the SAME
    `main._active_only` / `main._in_scope` filters the orchestrator applies.

    Deliberately NOT touched: enrichment_jail_bookings.py's OWN ROSTERS list
    (the jail_booking_new column -- cross-referencing existing board owners
    against jail rosters by name). That is a separate, heavier full-board
    matching pass with its own history of subtle bugs (see
    project_jail_booking_new_ran_detector_fix_2026-11-16.md); landing the
    jail_booking column's own 8 rows here is the scoped, time-boxed piece
    round 16 could safely verify end to end. jail_booking_new's own
    cross-reference pass for these 8 counties is left for a future round.

BOARD I/O: board_stream.iter_board_rows() for the pre-check (read-only) +
web_artifact.board_lock() + append_new_rows() for the write -- never
load_board()/write_artifact() on this board size.

    python scripts/backfill_jail_booking_round12_13_catchup.py --dry-run
    python scripts/backfill_jail_booking_round12_13_catchup.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.http_client import install_hard_sigint_kill  # noqa: E402
from foreclosure_scraper.main import _active_only, _in_scope  # noqa: E402
from foreclosure_scraper.scrapers.national import jail_bookings as _jb  # noqa: E402
from foreclosure_scraper.web_artifact import append_new_rows, board_lock  # noqa: E402

SOURCE = "national.jail_bookings"
HORIZON_DAYS = 120
# A dry run 2026-11-17 timed out 4/8 targets at 60s: _fetch_citizen_connect pages through
# ~60 pages max with a 0.3s politeness sleep + per-request retries between them, so a
# ~300-in-custody county (Dorchester/Sampson/Surry/Edgecombe all are) genuinely needs more
# than 60s total even with nothing wrong on the vendor's end -- the 3 CC counties AND
# Alexander's p2c_centralsquare that finished inside 60s were all the smaller ones (<=154).
_FETCH_TIMEOUT_S = 240.0

# The exact 8 ROSTERS tuples added by commits 50cda501 (round 12) and
# 6221208f (round 13) -- verified against the live file, not re-typed from
# the commit messages.
_TARGETS: list[tuple[str, str, str, str]] = [
    ("NC", "Scotland", "citizen_connect", "ScotlandCoNC|"),
    ("SC", "Dorchester", "citizen_connect", "DorchesterCoSC|"),
    ("NC", "Sampson", "citizen_connect", "SampsonCoNC|"),
    ("NC", "Surry", "citizen_connect", "SurryCoNC|"),
    ("NC", "Edgecombe", "citizen_connect", "EdgecombeCoNC|"),
    ("NC", "Greene", "citizen_connect", "GreeneCoNC|"),
    ("NC", "Yancey", "citizen_connect", "YanceyCoNC|"),
    ("NC", "Alexander", "p2c_centralsquare",
     "https://alexandercountyso.policetocitizen.com|532"),
]

# Fail loudly if these ever drift from the live ROSTERS list (e.g. someone
# edits/removes one before this script is run) rather than silently fetching
# a stale/wrong target.
_ROSTERS_SET = {(s, c, v, t) for s, c, v, t in _jb.ROSTERS}
for _t in _TARGETS:
    assert _t in _ROSTERS_SET, f"{_t} is no longer in jail_bookings.ROSTERS verbatim"


def _count_existing(docs: Path) -> dict[tuple[str, str], int]:
    """{(state, county): existing row count from SOURCE} via one streaming pass."""
    wanted = {(s, c) for s, c, _v, _t in _TARGETS}
    counts: dict[tuple[str, str], int] = {k: 0 for k in wanted}
    for rec in iter_board_rows(docs / "listings.json.gz"):
        key = (rec.get("state"), rec.get("county"))
        if key in wanted and rec.get("source") == SOURCE:
            counts[key] += 1
    return counts


async def _fetch_new() -> list:
    out: list = []
    for state, county, vendor, target in _TARGETS:
        try:
            inmates = await asyncio.wait_for(
                _jb._fetch_roster(state, county, vendor, target), timeout=_FETCH_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 - report, keep going
            print(f"  [FAIL] {state}/{county}: {e!r}")
            continue
        print(f"  [OK]   {state}/{county} ({vendor}): {len(inmates):,} in custody")
        out.extend(_jb._to_listing(rec, state, county) for rec in inmates)
    return out


def main() -> int:
    install_hard_sigint_kill(reason="backfill_jail_booking_round12_13_catchup")

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"

    existing = _count_existing(docs)
    print("pre-check: existing board rows from source=national.jail_bookings, per target county:")
    for (s, c), n in existing.items():
        print(f"  {s}/{c}: {n:,}")

    print(f"\nlive-fetching {len(_TARGETS)} roster targets...")
    rows = asyncio.run(_fetch_new())
    print(f"\ntotal scraped: {len(rows):,}")

    kept = [r for r in rows if _active_only(r, HORIZON_DAYS) and _in_scope(r)]
    print(f"kept after _active_only + _in_scope: {len(kept):,}")
    if not kept:
        print("\nnothing to land -- aborting.")
        return 1

    empty_url = sum(1 for li in kept if not li.source_url)
    print(f"rows with empty source_url (should be 0 after the _to_listing fix): {empty_url:,}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        for li in kept[:5]:
            print("  sample:", li.state, li.county, li.source_url, li.case_number)
        return 0

    # wait= : the live fetch above costs ~7 min of real wall time against 8 courteous-pace
    # vendor hosts, so a bare instant-fail board_lock() (the default, correct for a scheduled
    # pass that should skip rather than queue) would throw away that fetch on any transient
    # lock contention. A sibling agent's backfill_incarceration.py held the lock for 4+ min on
    # attempt #2 (BoardLockBusy) -- wait out a reasonable window instead of re-fetching.
    with board_lock(REPO, owner="backfill_jail_booking_round12_13_catchup",
                     wait=600.0, poll=15.0):
        result = append_new_rows(
            kept, {"backfill_jail_booking_round12_13_catchup": f"{len(kept)} rows"},
            docs_dir=docs)
    print("\n=== append_new_rows result ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
