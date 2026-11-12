#!/usr/bin/env python3
"""Run enrichment_owner_cluster.enrich_owner_cluster() board-wide.

100% offline, no network calls. Groups board rows by (surname, first given
name, county, state) -- excluding entities -- and tags every member of a
2+-distinct-property group with raw['owner_cluster']. Direct implementation
of Dirty Deeds Tier A #2 (docs/dirty_deeds_synthesis_2026-09-10.md): "One
death touching 25 parcels is worth more than 25 unrelated leads."

    python scripts/backfill_owner_cluster.py --dry-run
    python scripts/backfill_owner_cluster.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_owner_cluster import enrich_owner_cluster  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_owner_cluster")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        before = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("owner_cluster"))
        print(f"owner_cluster before: {before:,}")

        if args.dry_run:
            stats = enrich_owner_cluster(rows)
            print(f"\n(dry run -- computed but not persisted): {stats}")
            print("\nDRY RUN — nothing written.")
            return 0

        stats = enrich_owner_cluster(rows)
        after = sum(1 for li in rows if isinstance(li.raw, dict) and li.raw.get("owner_cluster"))
        print(f"\nstats: {stats}")
        print(f"owner_cluster after: {after:,} (+{after - before:,})")

        # Surface the biggest clusters for a sanity read.
        seen = set()
        biggest = []
        for li in rows:
            oc = isinstance(li.raw, dict) and li.raw.get("owner_cluster")
            if oc and oc["cluster_id"] not in seen:
                seen.add(oc["cluster_id"])
                biggest.append(oc)
        biggest.sort(key=lambda c: -c["cluster_size"])
        print("\nTop 15 clusters by size:")
        for c in biggest[:15]:
            print(f"  {c['cluster_id']}: size={c['cluster_size']} confidence={c['confidence']} "
                  f"total_value={c['total_value']} sources={set(c['member_sources'])}")

        write_artifact(rows, {"backfill_owner_cluster": stats}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
