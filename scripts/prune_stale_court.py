#!/usr/bin/env python
"""Prune genuinely-old-and-dead manual SC PublicIndex court-export leads.

The manual court-export lane (source == counties_sc.sc_public_index_export) is
operator-saved SC PublicIndex result pages ingested offline. Some of those rows
are stale 2025 cases that never carried a sale_date and have not been refreshed
in months — dead weight on the board. This prunes ONLY that narrow, provable set:

    source     == counties_sc.sc_public_index_export   (the manual export lane)
    first_seen  year <= PRUNE_MAX_FIRST_SEEN_YEAR       (default 2025)
    sale_date  is None                                  (never got a sale date)
    last_seen  older than PRUNE_STALE_DAYS              (default 120) days ago

DRY-RUN by default: prints the matching leads + counts by source/county and
writes nothing. Only PRUNE_WRITE=1 actually loads the board, drops the matches,
and rewrites the artifact (through load_board/write_artifact so the lazy comps/
vision sidecar round-trips safely).

Env knobs:
    PRUNE_MAX_FIRST_SEEN_YEAR  first_seen year at/below which a lead is eligible (default 2025)
    PRUNE_STALE_DAYS           days since last_seen to count as stale (default 120)
    PRUNE_WRITE=1              perform the write (default: dry-run only)

Usage:
    python scripts/prune_stale_court.py            # dry-run (safe)
    PRUNE_WRITE=1 python scripts/prune_stale_court.py
"""
from __future__ import annotations

import collections
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import load_board, write_artifact  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs"

# The one lane this script is allowed to prune. Kept as a named constant so the
# predicate can never accidentally match another (higher-value) source.
STALE_COURT_SOURCE = "counties_sc.sc_public_index_export"

DEFAULT_MAX_FIRST_SEEN_YEAR = 2025
DEFAULT_STALE_DAYS = 120


def is_stale_court(
    li: Listing,
    *,
    now: datetime,
    max_first_seen_year: int = DEFAULT_MAX_FIRST_SEEN_YEAR,
    stale_days: int = DEFAULT_STALE_DAYS,
    require_stale_last_seen: bool = True,
) -> bool:
    """Pure predicate: is this lead a genuinely old + dead manual-court-export row?

    Always requires:
      - source is exactly the manual SC PublicIndex export lane,
      - it never carried a sale_date,
      - first_seen year is at/below max_first_seen_year.

    The last_seen>stale_days check is OPT-OUT because on this specific lane
    last_seen is unreliable: a board carry-forward stamps last_seen=today on
    every re-merge, so a 2025 lead reads as "seen today" without any fresh court
    confirmation. first_seen never gets bumped, so it is the honest age signal.
    Set require_stale_last_seen=False (PRUNE_IGNORE_LAST_SEEN=1) to prune on
    first_seen alone — the correct default for this carry-forward-bumped lane.
    """
    if li.source != STALE_COURT_SOURCE:
        return False
    if li.sale_date is not None:
        return False
    first_seen = li.first_seen
    if first_seen is None or first_seen.year > max_first_seen_year:
        return False
    if not require_stale_last_seen:
        return True
    last_seen = li.last_seen
    if last_seen is None:
        return False
    cutoff = now - timedelta(days=stale_days)
    return last_seen < cutoff


def _county_of(li: Listing) -> str:
    return (li.county or "?").strip() or "?"


def main() -> int:
    max_year = int(os.environ.get("PRUNE_MAX_FIRST_SEEN_YEAR", DEFAULT_MAX_FIRST_SEEN_YEAR))
    stale_days = int(os.environ.get("PRUNE_STALE_DAYS", DEFAULT_STALE_DAYS))
    do_write = os.environ.get("PRUNE_WRITE") == "1"
    # Default to first_seen-only on this lane: its last_seen is carry-forward noise.
    require_stale = os.environ.get("PRUNE_IGNORE_LAST_SEEN", "1") != "1"
    now = datetime.utcnow()

    listings = load_board(DOCS)
    print(f"loaded {len(listings)} listings", flush=True)
    print(
        f"criteria: source={STALE_COURT_SOURCE} first_seen_year<={max_year} "
        f"sale_date=None last_seen>{stale_days}d old (now={now.date()})",
        flush=True,
    )

    stale = [li for li in listings if is_stale_court(
        li, now=now, max_first_seen_year=max_year, stale_days=stale_days,
        require_stale_last_seen=require_stale)]

    by_source = collections.Counter(li.source for li in stale)
    by_county = collections.Counter(_county_of(li) for li in stale)

    print(f"\nMATCHED {len(stale)} stale-court leads to prune:", flush=True)
    for li in stale:
        fs = li.first_seen.date() if li.first_seen else "?"
        ls = li.last_seen.date() if li.last_seen else "?"
        print(f"  - {_county_of(li):<14} {li.case_number or '?':<20} "
              f"first_seen={fs} last_seen={ls} :: {(li.street_address or '(no address)')[:48]}",
              flush=True)

    print("\nby source:", dict(by_source), flush=True)
    print("by county:", dict(by_county), flush=True)

    if not do_write:
        print(f"\nDRY-RUN — nothing written. Set PRUNE_WRITE=1 to drop these "
              f"{len(stale)} leads.", flush=True)
        return 0

    if not stale:
        print("\nnothing to prune; leaving board untouched.", flush=True)
        return 0

    drop_ids = {id(li) for li in stale}
    kept = [li for li in listings if id(li) not in drop_ids]
    summary = {
        "by_source": dict(collections.Counter(li.source for li in kept if li.source)),
        "notes": (f"pruned {len(stale)} stale manual SC-court-export leads "
                  f"(first_seen<={max_year}, no sale_date, last_seen>{stale_days}d)"),
    }
    lp, mp = write_artifact(kept, summary, docs_dir=DOCS)
    print(f"\nwrote {lp} ({lp.stat().st_size:,} bytes) + {mp.name} | "
          f"{len(listings)} -> {len(kept)} kept ({len(stale)} pruned)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
