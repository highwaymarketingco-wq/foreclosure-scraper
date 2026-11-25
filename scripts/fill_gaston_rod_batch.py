#!/usr/bin/env python3
"""Bounded, checkpointed Gaston NC ROD lien-existence enrichment.

fill_gaston_rod.py (the original) calls load_board() + write_artifact() over the
whole board just to patch a scoped subset of NC/Gaston rows -- the same double-
materialization pattern already fixed elsewhere this session (see
patch_existing_rows()'s own docstring, and resolver_backfill_parcel.py for the
reference). 24,531 Gaston rows need this check (measured 2026-11-24); that's
many hours of real network time at the pacing this enrichment needs, not a
one-shot run, so this takes --max-lookups to process ONE bounded batch per
invocation and checkpoint just those rows via patch_existing_rows().

enrich_gaston_rod() itself (enrichment_gaston_rod.py) is unchanged -- it already
opens one Cloudflare-solved browser session and loops every target it's given,
so a single call per invocation (not per-chunk) is correct here: splitting into
multiple internal chunks would just pay the Cloudflare-solve overhead (~5-15s)
repeatedly for no benefit.

Usage:
    python scripts/fill_gaston_rod_batch.py --max-lookups 300
    python scripts/fill_gaston_rod_batch.py --max-lookups 300 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
# This board (5.9GB+) is over patch_existing_rows()'s default 2300MB ceiling.
# patch_existing_rows() is measurably cheap per row regardless of board size
# (see BOARD_PATCH_MAX_SOURCE_MB's own comment in web_artifact.py) -- this is
# the sanctioned override for one supervised run, same pattern used by every
# other patch-based script this session (lrcpwa_refresh.py, the VM wrappers).
os.environ.setdefault("BOARD_PATCH_ALLOW_LARGE", "1")

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_gaston_rod import enrich_gaston_rod  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402


def _unchecked_gaston_rows(docs: Path):
    """Shared scan used by both passes in _collect_targets() below -- NC/Gaston
    rows with an owner_name and no raw['rod'] yet, streamed and validated into
    real Listings."""
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if rec.get("state") != "NC" or not rec.get("owner_name"):
            continue
        county = (rec.get("county") or "").strip().upper().replace(" COUNTY", "")
        if county != "GASTON":
            continue
        raw = rec.get("raw")
        if isinstance(raw, dict) and "rod" in raw:
            continue
        try:
            yield Listing.model_validate(rec)
        except Exception:  # noqa: BLE001 - a malformed row must not crash the collector
            continue


def _collect_targets(docs: Path, cap: int) -> list[Listing]:
    """Up to `cap` unchecked NC/Gaston rows, excluding any whose dedupe_key()
    is shared with another unchecked row in the same pool.

    FIXED 2026-11-25: a prior version fed every unchecked row straight into
    enrich_gaston_rod() regardless of identity. main()'s own
    `pre_keys = {li.dedupe_key(): li for li in targets}` then silently
    collapsed any rows sharing a key down to one survivor, and
    patch_existing_rows()'s unsafe-identity guard correctly refuses to write
    that survivor back whenever its key is genuinely non-unique board-wide
    (confirmed live: a cluster of Gaston rows with no parcel_id/address/
    case_number all fall through dedupe_key()'s final `url:{source_url}`
    branch, sharing one identity because they were all originally sourced
    from the same informational page). Since nothing about them ever gets
    written to disk, the exact same cluster was re-selected and re-searched
    every single cron tick -- 4 consecutive 10-minute batches with identical
    stats and zero real writes, confirmed via logs/gaston_rod_batch_continuous.log.
    Counting dedupe_key() occurrences up front and excluding non-unique rows
    from the selection pool entirely stops wasting rate-limited search budget
    on rows that could never be safely patched anyway, freeing it for the
    rest of the ~24,500-row backlog that CAN be written back."""
    key_counts: Counter[str] = Counter(li.dedupe_key() for li in _unchecked_gaston_rows(docs))

    targets: list[Listing] = []
    skipped_unsafe = 0
    for li in _unchecked_gaston_rows(docs):
        if key_counts[li.dedupe_key()] > 1:
            skipped_unsafe += 1
            continue
        targets.append(li)
        if len(targets) >= cap:
            break
    if skipped_unsafe:
        print(f"skipped {skipped_unsafe:,} rows up front: dedupe_key shared with "
              f"another unchecked row (can never be safely patched individually)")
    return targets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-lookups", type=int, default=300,
                     help="How many Gaston rows to check this run (default 300).")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs = REPO / "docs"
    targets = _collect_targets(docs, args.max_lookups)
    print(f"targets this run: {len(targets):,} (cap {args.max_lookups:,})")
    if not targets:
        return 0

    # Identity captured before enrich_gaston_rod() mutates li.raw -- dedupe_key()
    # never reads raw, so order doesn't matter here, but matching the reference
    # pattern (resolver_backfill_parcel.py) keeps this consistent and safe if
    # that invariant ever changes.
    pre_keys = {li.dedupe_key(): li for li in targets}

    stats = asyncio.run(enrich_gaston_rod(targets, max_lookups=args.max_lookups))
    print("enrich_gaston_rod stats:", stats)

    patches: dict[str, dict] = {}
    for key, li in pre_keys.items():
        if isinstance(li.raw, dict) and li.raw.get("rod"):
            patches[key] = {"raw": {"rod": li.raw["rod"]}}

    print(f"rows with a real rod result to patch: {len(patches):,}")
    if args.dry_run or not patches:
        print("DRY RUN or nothing to patch -- not writing." if args.dry_run else "nothing to patch.")
        return 0

    with board_lock(REPO, owner="fill_gaston_rod_batch", wait=1800, poll=10):
        result = patch_existing_rows(
            patches, {"notes": "Gaston NC ROD lien-existence by owner name (batched)"},
            docs_dir=docs)
    print("patch result:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
