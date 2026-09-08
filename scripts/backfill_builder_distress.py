#!/usr/bin/env python3
"""Apply the builder_distress signal that ingest_liensnc.py defines but never populated.

ingest_liensnc.py's own docstring states the distress signal is a CLUSTER, not a
lone filing:

    "a project with 'Active Related Filings? = Yes' (multiple contractors preserving
     lien rights on one job) or the same address appearing on multiple rows = an
     over-leveraged flipper/builder running out of capital, contractors lining up to
     file mechanic's liens = a motivated seller BEFORE bank foreclosure"

Everything downstream is already wired -- enrichment_lead_signals.py:114 reads
raw['builder_distress'] and emits the 'builder_distress' signal, and
web_artifact.py:484 ships it to the dashboard -- but the flag is set on 0 of the
56,452 liensnc rows on the published board.

Two reasons it was missing: these rows entered by a path that skipped the flag,
and the address-cluster half of the test was unmeasurable until the raw re-parse
(scripts/backfill_liensnc_raw.py) recovered street addresses.

Uses the SAME rule as the ingester (cluster = address seen >= 2; related =
"Active Related Filings? == Yes"), writes the SAME shape, then recomputes lead
signals so distress_stack / signal_stack / intent_score pick it up. Fills only --
never adds or removes a row, so the count guard is untouched.

    python scripts/backfill_builder_distress.py --dry-run
    python scripts/backfill_builder_distress.py
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
DOCS = REPO / "docs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.web_artifact import load_board, write_artifact, board_lock
    from foreclosure_scraper.enrichment_lead_signals import enrich_lead_signals

    with board_lock(DOCS):
        board = load_board(DOCS)
        rows = [li for li in board
                if "liensnc" in str(getattr(li, "source", "") or "")]
        print(f"board {len(board):,} | liensnc {len(rows):,}")

        # cluster = same property address on 2+ filings (the ingester's rule)
        counts: collections.Counter = collections.Counter()
        for li in rows:
            a = (getattr(li, "street_address", None) or "").strip().upper()
            if a:
                counts[a] += 1

        st = collections.Counter()
        touched = []
        for li in rows:
            raw = li.raw if isinstance(getattr(li, "raw", None), dict) else {}
            blk = raw.get("liensnc") or {}
            a = (getattr(li, "street_address", None) or "").strip().upper()
            cluster = bool(a) and counts.get(a, 0) >= 2
            related = str(blk.get("related_filings", "")).strip().lower() == "yes"
            if not (cluster or related):
                continue
            if not raw.get("builder_distress"):
                raw["builder_distress"] = {
                    "related_filings": related,
                    "cluster": cluster,
                    "source": "liensnc",
                }
                st["flagged"] += 1
                st["both"] += 1 if (cluster and related) else 0
                st["related_only"] += 1 if (related and not cluster) else 0
                st["cluster_only"] += 1 if (cluster and not related) else 0
            li.raw = raw
            touched.append(li)

        print(f"\nbuilder_distress flagged: {st['flagged']:,}")
        print(f"   both (cluster AND related): {st['both']:,}   <- strongest")
        print(f"   related filings only      : {st['related_only']:,}")
        print(f"   address cluster only      : {st['cluster_only']:,}")

        if args.dry_run:
            print("\n--dry-run: nothing written")
            return 0

        # Re-run signals so distress_stack / signal_stack / intent_score update.
        stats = enrich_lead_signals(board)
        print(f"\nenrich_lead_signals: {stats}")

        summary = {
            "by_source": dict(collections.Counter(
                li.source for li in board if getattr(li, "source", None))),
            "notes": (f"builder_distress backfill: {st['flagged']} liensnc leads "
                      f"flagged (cluster/related filings)"),
        }
        lp, _ = write_artifact(board, summary, docs_dir=DOCS)
        print(f"board rows {len(board):,} (unchanged) | wrote {lp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
