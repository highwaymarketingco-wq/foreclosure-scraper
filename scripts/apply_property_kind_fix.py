#!/usr/bin/env python3
"""Apply the property_kind LAND-correction to the published board.

The cascade fix lives in enrichment_property_kind, but a code fix only changes
what the NEXT run produces. The 1,369 houses typed LAND stay on the board, with
rehab_tier "land" and zero rehab deducted, until a pass actually writes them.
This is that pass.

Runs enrich_property_kind, then recomputes calc + grade on every corrected lead
so rehab, ARV and the strategy tag reflect the new kind (leaving them stale would
publish a single_family with land economics attached).

Takes the REAL board lock: board_lock(REPO), not board_lock(DOCS). Passing DOCS
builds docs/logs/.board.lock, which excludes nothing, and a writer holding that
runs concurrently with the 4h vision pass and has its work silently reverted.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
DOCS = REPO / "docs"


def main() -> int:
    from foreclosure_scraper.web_artifact import load_board, write_artifact, board_lock
    from foreclosure_scraper.enrichment_property_kind import enrich_property_kind
    from foreclosure_scraper.models import PropertyKind
    from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade

    with board_lock(REPO):
        board = load_board(DOCS)
        before = [li for li in board
                  if li.property_kind == PropertyKind.LAND
                  and li.bedrooms and (li.living_sqft or 0) > 400]
        ids = {id(li) for li in before}
        print(f"board {len(board):,} | land-with-a-house: {len(before):,}")

        enrich_property_kind(board)

        fixed = [li for li in board
                 if id(li) in ids and li.property_kind == PropertyKind.SINGLE_FAMILY]
        print(f"  corrected to single_family: {len(fixed):,}")

        # Kind drives rehab tier, ARV and strategy - recompute or the numbers
        # stay land economics on a house.
        regraded = 0
        for li in fixed:
            try:
                c = vcalc.compute(li)
                g = vgrade.grade(li, c)
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["calc"] = vcalc.to_dict(c)
                li.raw["grade"] = vgrade.to_dict(g)
                regraded += 1
            except Exception:  # noqa: BLE001
                pass
        print(f"  recomputed calc + grade on: {regraded:,}")

        still = sum(1 for li in board
                    if li.property_kind == PropertyKind.LAND
                    and li.bedrooms and (li.living_sqft or 0) > 400)
        print(f"  remaining contradictions: {still:,}")

        summary = {
            "by_source": dict(collections.Counter(
                li.source for li in board if getattr(li, "source", None))),
            "notes": (f"property_kind: {len(fixed)} houses corrected from LAND, "
                      f"{regraded} regraded"),
        }
        lp, _ = write_artifact(board, summary, docs_dir=DOCS)
        print(f"\nboard rows {len(board):,} (unchanged) | wrote {lp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
