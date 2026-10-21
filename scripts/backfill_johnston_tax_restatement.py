#!/usr/bin/env python3
"""One-time backfill: restate tax_aging_surfaced + two_year_delinquent for Johnston NC's
delinquent-tax-crosswalk-sourced rows (scrapers/counties_nc/johnston_delinquent_tax_crosswalk.py,
landed 2026-10-20, 185 real board rows) -- pure compute, NO network call at all.

WHY THIS EXISTS (docs/gap_matrix/gap_list_2026-10-21.csv: NC Johnston tax_aging_surfaced AND
two_year_delinquent, 3,485 est_rows_affected each, built=no). Both columns read from data the
crosswalk already fetched and landed; nothing had re-derived them since.

  * tax_aging_surfaced: the crosswalk's raw['johnston_delinquent_tax_crosswalk']['total_delinquent']
    already normalizes into raw['tax_owed'] via enrichment_tax_owed.py's existing, generic,
    unmodified _SOURCES mapping -- just needed that pure function (and enrichment_tax_aging's
    own, equally pure, downstream read of it) actually RUN over these rows once. Same chain-break
    shape already fixed tonight for Wake/Randolph (see commit 71c26ca6's own message).
  * two_year_delinquent: needed a small new pure restatement (enrichment_johnston_two_year_
    delinquent.py, built alongside this script) reading the SAME crosswalk block's
    delinquent_by_year -- no existing generic deriver covered this source's exact field names.

BOARD I/O: board_stream.iter_board_rows() once, keeping only Johnston NC rows that carry
raw['johnston_delinquent_tax_crosswalk'] (185 of them, confirmed by a live board scan), then ONE
patch_existing_rows() call under board_lock(), lock scoped to only the final write
(wait=600/poll=10) per tonight's established lock-placement discipline.

    python scripts/backfill_johnston_tax_restatement.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_johnston_tax_restatement.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_johnston_two_year_delinquent import (  # noqa: E402
    SRC_KEY, enrich_johnston_two_year_delinquent,
)
from foreclosure_scraper.enrichment_tax_aging import enrich_tax_aging  # noqa: E402
from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

_WATCH_KEYS = ("tax_owed", "tax_aging_surfaced", "tax_aging_high", "two_year_delinquent")


def _light(rec: dict) -> Listing:
    li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
    li.raw = dict(rec.get("raw") or {})
    return li


def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], int]:
    """{dedupe_key: light_listing} of every Johnston NC row carrying the crosswalk block, +
    total rows streamed."""
    cands: dict[str, Listing] = {}
    total = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        total += 1
        if str(rec.get("state") or "").upper() != "NC":
            continue
        county = (rec.get("county") or "").replace(" County", "").strip()
        if county != "Johnston":
            continue
        raw = rec.get("raw")
        if not isinstance(raw, dict) or not isinstance(raw.get(SRC_KEY), dict):
            continue
        li = _light(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        cands[key] = li
    return cands, total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"
    candidates, total_rows = _collect_candidates(docs)
    print(f"board rows streamed: {total_rows:,}")
    print(f"Johnston NC crosswalk-sourced candidates: {len(candidates):,}")
    if not candidates:
        print("\nnothing to do.")
        return 0

    before = {key: dict(li.raw) for key, li in candidates.items()}

    listings = list(candidates.values())
    tyd_stats = enrich_johnston_two_year_delinquent(listings)
    owed_stats = enrich_tax_owed(listings)
    aging_stats = enrich_tax_aging(listings)
    print(f"\nenrich_johnston_two_year_delinquent: {tyd_stats}")
    print(f"enrich_tax_owed: {owed_stats}")
    print(f"enrich_tax_aging: {aging_stats}")

    patches: dict[str, dict] = {}
    for key, li in candidates.items():
        b = before[key]
        raw_patch = {k: li.raw.get(k) for k in _WATCH_KEYS if li.raw.get(k) != b.get(k)}
        if raw_patch:
            patches[key] = {"raw": raw_patch}
    print(f"\npatches staged: {len(patches):,}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written. (Note: every step above is pure compute, no "
              "network call at all -- --dry-run here only controls whether the result is "
              "WRITTEN to the board.)")
        return 0
    if not patches:
        print("\nnothing to do.")
        return 0

    size_state = board_patch_size_state(docs)
    if not size_state["ok"]:
        print(f"\nREFUSING: {size_state['reason']}. Re-run with BOARD_PATCH_ALLOW_LARGE=1 "
              f"under supervision.")
        return 1

    with board_lock(REPO, owner="johnston_tax_restatement_backfill", wait=600, poll=10):
        pstats = patch_existing_rows(
            patches, {"backfill_johnston_tax_restatement": tyd_stats}, docs_dir=docs)
    print(f"\npatch result: {pstats}")
    print(f"patched {pstats['applied']}/{len(patches)} rows "
          f"(existing board: {pstats['existing']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
