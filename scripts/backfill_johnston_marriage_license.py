#!/usr/bin/env python3
"""One-time backfill: land the new Johnston NC Tyler EagleWeb marriage-type sweep
(rod/county_sweeps.EagleWebMarriageReader, enrichment_county_lien_sweep.SWEEP_COUNTIES, built
2026-10-21) onto the already-published board.

WHY. The gap list named "Tyler EagleWeb (erec.johnstonnc.com/recorder/web)" for Johnston's
marriage_license column (1,914 applicable rows). LIVE-VERIFIED 2026-10-21: this county's EagleWeb
register was already wired for its DEED side (rod/nc_tyler.py's COUNTIES, FORECLOSURE_NC_TYLER_ROD)
but marriage records need a different, TYPE-filtered search (BookTypeID='M'), not the per-owner
deed path -- a blank-name, date-windowed guest search pages past the per-owner guest-result cap
cleanly (1,340 real 2024 marriage records, 14 pages, no login, no CAPTCHA). Built as
rod/county_sweeps.EagleWebMarriageReader, the same county-wide-sweep architecture already serving
Beaufort's/Watauga's CCS LRSearch Marriages index -- one sweep (cached in data/county_sweeps/,
git-ignored) then serves every Johnston board row, instead of one per-owner search each.

enrich_county_lien_sweep() is ALREADY internally scoped (SWEEP_COUNTIES keys by (state, county))
and already idempotent for marriage (a licence found by another source is never overwritten by a
later no_match). This script's own pre-filter (state=="NC", county=="Johnston", owner present)
just avoids materializing the other ~447K board rows into Listing objects, via the same
board_stream.iter_board_rows() + patch_existing_rows() pattern every backfill this session uses
(never load_board()/write_artifact() at this board's size).

    python scripts/backfill_johnston_marriage_license.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_johnston_marriage_license.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_county_lien_sweep import enrich_county_lien_sweep  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

#: _APPEND_SIG_FIELDS does not carry owner_name (it's an identity-signature tuple, not a full
#: field list) -- enrich_county_lien_sweep()'s per-row owner lookup needs it.
_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name")
COUNTY = "Johnston"


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], int]:
    """{dedupe_key: light_listing} of every Johnston NC row with a usable owner name, + total
    rows streamed. Unlike the marriage ENRICHER's own idempotent gate (which skips a row that
    already carries a FOUND licence, not a mere 'no_match' stamp), this backfill re-sweeps every
    owner-bearing row each run -- the sweep itself is cheap once cached, and a 'no_match' from a
    narrower cached window should not permanently block a wider one from ever re-checking."""
    cands: dict[str, Listing] = {}
    total = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        total += 1
        if str(rec.get("state") or "").upper() != "NC":
            continue
        county = (rec.get("county") or "").replace(" County", "").strip()
        if county != COUNTY:
            continue
        owner = rec.get("owner_name") or rec.get("defendant")
        if not owner:
            continue
        li = _light(rec)
        li.owner_name = owner           # enrich_county_lien_sweep() reads li.owner_name specifically
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
    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="johnston_marriage_backfill")
    with lock:
        candidates, total_rows = _collect_candidates(docs)
        print(f"board rows streamed: {total_rows:,}")
        print(f"Johnston NC candidates (owner present): {len(candidates):,}")

        if not candidates:
            print("\nnothing to do.")
            return 0

        before = {key: (li.raw.get("marriage_license") if isinstance(li.raw, dict) else None)
                 for key, li in candidates.items()}

        print("\n=== running the REAL enrich_county_lien_sweep() against the live register ===")
        stats = asyncio.run(enrich_county_lien_sweep(list(candidates.values())))
        print(f"\nstats: {stats}")

        patches: dict[str, dict] = {}
        for key, li in candidates.items():
            after = li.raw.get("marriage_license") if isinstance(li.raw, dict) else None
            if after is not None and after != before[key]:
                patches[key] = {"raw": {"marriage_license": after}}

        found = sum(1 for p in patches.values() if p["raw"]["marriage_license"].get("status") in ("found", "possible"))
        no_match = sum(1 for p in patches.values() if p["raw"]["marriage_license"].get("status") == "no_match")
        print(f"\npatches staged: {len(patches):,} (found/possible: {found:,}, no_match: {no_match:,})")

        if args.dry_run:
            print("\nDRY RUN -- nothing written. (enrich_county_lien_sweep() above still hits "
                  "the real live register -- this module has no network-free dry-run mode; "
                  "--dry-run here only controls whether the result is WRITTEN to the board.)")
            return 0
        if not patches:
            print("\nnothing to patch this run.")
            return 0

        size_state = board_patch_size_state(docs)
        if not size_state["ok"]:
            print(f"\nREFUSING: {size_state['reason']}. Re-run with BOARD_PATCH_ALLOW_LARGE=1 "
                  f"under supervision.")
            return 1

        pstats = patch_existing_rows(
            patches, {"backfill_johnston_marriage_license": stats}, docs_dir=docs)
        print(f"\npatch result: {pstats}")
        print(f"patched {pstats['applied']}/{len(patches)} rows "
              f"(existing board: {pstats['existing']:,})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
