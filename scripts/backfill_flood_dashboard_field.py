#!/usr/bin/env python3
"""Derive raw['flood'] (the field the dashboard actually reads) from
raw['flood_zone'] (what today's backfill populated), for every row that has
the latter but not the former. Zero network calls.

REAL BUG FOUND 2026-09-16: this codebase carries TWO separate, functionally
identical FEMA-NFHL flood enrichers that were never reconciled:
  - enrichment_flood.py       -- wired into main.py, writes raw['flood'] =
                                  {zone, subtype, sfha_tf, in_sfha, static_bfe}.
                                  docs/dashboard.js's badges (line ~4717) and
                                  Risk & Environment panel (line ~5031) read
                                  ONLY this key.
  - enrichment_flood_zone.py  -- NOT wired into main.py, writes
                                  raw['flood_zone'] = {in_sfha, zone,
                                  zone_description, flood_risk}.

Today's flood_zone backfill (scripts/backfill_flood_zone.py) ran the SECOND,
dashboard-invisible module against the whole board (18.9% -> 85.6%), because
that was the one this session found via main.py-wiring search -- and missed
that the FIRST module already existed, was already wired in, and is the one
the UI actually renders. Net effect before this script: real, correct flood
data sitting on 150,310 rows, visible on the dashboard for only 29,234 of
them (16.7%).

Both enrichers query the identical free FEMA NFHL point-in-polygon service
for the identical purpose, so re-running enrich_with_flood from scratch
would just re-fetch data this board already has. Deriving raw['flood'] from
raw['flood_zone'] closes the gap for the ~121K already-covered rows with
zero new network calls; the small remainder genuinely outside flood_zone's
coverage will still get picked up by enrich_with_flood on a normal main.py
run (it only queries leads missing raw['flood'], so this script does not
block or duplicate that).

    python scripts/backfill_flood_dashboard_field.py --dry-run
    python scripts/backfill_flood_dashboard_field.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def _derive(flood_zone: dict) -> dict:
    return {
        "zone": flood_zone.get("zone"),
        "sfha_tf": bool(flood_zone.get("in_sfha")),
        "in_sfha": bool(flood_zone.get("in_sfha")),
        "note": flood_zone.get("zone_description"),
        "derived_from": "flood_zone_backfill",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_flood_dashboard_field")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        before = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("flood"))
        print(f"raw.flood before: {before:,}")

        targets = [
            li for li in rows
            if isinstance(li.raw, dict) and li.raw.get("flood_zone") and not li.raw.get("flood")
        ]
        print(f"derivable (has flood_zone, missing flood): {len(targets):,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        for li in targets:
            li.raw["flood"] = _derive(li.raw["flood_zone"])

        after = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("flood"))
        print(f"raw.flood after: {after:,} (+{after - before:,})")

        write_artifact(rows, {"backfill_flood_dashboard_field": len(targets)}, docs_dir=REPO / "docs")
        print(f"wrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
