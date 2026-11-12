#!/usr/bin/env python3
"""Backfill REAL heated sqft (+ beds/baths) from county assessor cards.

WHY. ARV is built from $/sqft rehab tiers on ``living_sqft``; without true sqft,
calc caps ARV confidence at MEDIUM and falls back to a crude bid/tax proxy. The
board un-freeze left ~12k built homes in card-covered counties (Rutherford 4.7k,
Buncombe 3.1k, Lincoln, Anderson, Laurens, ...) still missing sqft. The nightly
run chews these at ASSESSOR_CARD_MAX/run; this script grinds the backlog on
demand in daylight, bounded + resumable (the enricher skips leads that already
have true sqft, so each pass advances the queue).

Card render is slow (~seconds/lead), so pick --max for the time you have
(~1500/pass is a reasonable daytime chunk). Filling sqft clears the ESTIMATE
flag, so touched leads are re-graded here -> their ARV can move to HIGH.

SAFETY: board-lock-guarded (won't write while a scrape run holds the lock).

USAGE:
    python scripts/sqft_backfill.py --dry-run          # count eligible, no write
    python scripts/sqft_backfill.py --max 1500         # fill up to 1500, then write
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

DOCS = "docs"


def _eligible(li) -> bool:
    """Built (not land) lead whose sqft is missing or only an estimate."""
    kind = str(getattr(li, "property_kind", "") or "").lower()
    if "land" in kind or "vacant" in kind:
        return False
    return (not getattr(li, "living_sqft", None)) or bool(
        getattr(li, "living_sqft_estimated", False))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=1500, help="max cards to render this pass")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # The enricher reads this at import/run time to bound its work.
    os.environ["ASSESSOR_CARD_MAX"] = str(args.max)
    os.environ.setdefault("ASSESSOR_CARD_ON", "1")

    from foreclosure_scraper.web_artifact import load_board, write_artifact, board_lock
    from foreclosure_scraper.enrichment_assessor_card import enrich_assessor_card
    from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade

    board = load_board(DOCS)
    elig = [li for li in board if _eligible(li)]
    by_county = collections.Counter(getattr(li, "county", "?") for li in elig)
    print(f"board: {len(board)} | eligible (built, missing/estimate sqft): {len(elig)}")
    print("top eligible counties:")
    for co, c in by_county.most_common(12):
        print(f"   {c:5d}  {co}")
    print(f"this pass will render up to {args.max} cards.")

    if args.dry_run:
        print("DRY RUN — no render, no write.")
        return 0

    before = sum(1 for li in board if getattr(li, "living_sqft", None)
                 and not getattr(li, "living_sqft_estimated", False))

    with board_lock(owner="sqft_backfill"):
        # re-load inside the lock so we fold the freshest sidecar
        board = load_board(DOCS)
        filled = enrich_assessor_card(board)
        print(f"enrich_assessor_card: {filled}")

        # Re-grade the leads the card just touched so new sqft lifts ARV confidence.
        touched = [li for li in board if isinstance(getattr(li, "raw", None), dict)
                   and "assessor_card" in li.raw]
        regraded = 0
        for li in touched:
            try:
                c = vcalc.compute(li)
                g = vgrade.grade(li, c)
                li.raw["calc"] = vcalc.to_dict(c)
                li.raw["grade"] = vgrade.to_dict(g)
                regraded += 1
            except Exception:  # noqa: BLE001
                pass
        print(f"re-graded {regraded} card-touched leads")

        after = sum(1 for li in board if getattr(li, "living_sqft", None)
                    and not getattr(li, "living_sqft_estimated", False))
        summary = {
            "by_source": dict(collections.Counter(
                li.source for li in board if getattr(li, "source", None))),
            "notes": f"sqft backfill: true-sqft {before} -> {after} (+{after-before})",
        }
        lp, mp = write_artifact(board, summary, docs_dir=DOCS)
        print(f"true-sqft leads: {before} -> {after} (+{after-before})")
        print(f"wrote {lp} ({lp.stat().st_size:,} bytes) | total: {len(board)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
