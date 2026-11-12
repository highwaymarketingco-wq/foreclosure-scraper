#!/usr/bin/env python3
"""Ingest Johnston County NC's delinquent-tax-file -> NC OneMap crosswalk producer
(counties_nc.johnston_delinquent_tax_crosswalk) into the live board.

BOARD I/O REWRITE (2026-10-20, follow-up to a real VM run of the original load_board()/
write_artifact() version: 2+ hours, 62GB of disk I/O for a 5GB dataset -- swap thrashing on the
VM's ~69MB/s block storage, 12 minutes of actual CPU time, killed safely mid-run). That version
ran the real dedupe() pass over [existing Johnston rows + new rows] -- correct in principle (a
scoped dedupe(), same trick scripts/ingest_greenville_delinquent_tax.py / ingest_dillon_
delinquent_tax.py use), but load_board()/write_artifact() themselves fully materialize and
re-serialize the WHOLE board (447,006+ rows), not just Johnston's -- exactly the double
materialization this board's size has made impractical, proven again tonight. The fix follows
scripts/backfill_vacant_lot_counties.py / scripts/resolver_backfill_parcel.py's established
pattern: stream the board ONCE via board_stream.iter_board_rows() (constant memory, never a
list[Listing] or list[dict] of the whole board), and write through web_artifact.
patch_existing_rows() / append_new_rows() instead of write_artifact().

THE SPLIT THIS PRODUCER NEEDS, UNLIKE A PURE BACKFILL. Every other patch_existing_rows()-based
script here targets rows ALREADY on the board (resolving a field on a row that exists). This
producer's own module docstring records that a resolved crosswalk lead is EXPECTED to collide
with an existing board row sometimes: ~8-25 of each run's ~187 resolved parcels already carry a
counties_nc.nc_heir_estate_parcels estate-lead row for the SAME PIN (a second, corroborating
angle on the same property -- a heir/estate signal AND a confirmed delinquent-tax balance), while
the rest are genuinely new. So this script does BOTH, in one pass:
  1. Stream the board once (iter_board_rows(), Johnston-NC rows only -- see
     _existing_johnston_keys()'s docstring for why that scoping is safe, not approximate) to
     build the set of dedupe_key()s already on the board.
  2. Classify each of the scraper's resolved Listings by exact dedupe_key() match against that
     set -- the SAME narrow identity patch_existing_rows() itself uses to find a row to mutate
     (see that function's docstring in web_artifact.py), so a lead classified "patch" here is
     guaranteed to be found there.
  3. patch_existing_rows() lands the matched group (merges the tax-lien raw block into the
     existing row -- nothing else on it is touched); append_new_rows() lands the rest (which
     still runs its OWN broader fuzzy dedupe safety net against the live board before adding
     anything -- see that function's docstring).

Neither of this script's siblings (ingest_greenville_delinquent_tax.py, ingest_dillon_
delinquent_tax.py) has been converted: both still call load_board()/write_artifact() and have
the SAME impracticality on this board's current size. Flagged, not fixed here -- out of this
script's scope.

    python scripts/ingest_johnston_tax_crosswalk.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 python scripts/ingest_johnston_tax_crosswalk.py
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
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.johnston_delinquent_tax_crosswalk import (  # noqa: E402
    RAW_KEY, JohnstonDelinquentTaxCrosswalk,
)
from foreclosure_scraper.web_artifact import (  # noqa: E402
    append_new_rows, board_lock, patch_existing_rows,
)

# Same narrow identity-field set scripts/backfill_vacant_lot_counties.py /
# scripts/resolver_backfill_parcel.py use to compute a dedupe_key() off a raw board-row dict
# without validating it into a full Listing.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")


def _is_johnston_nc(rec: dict) -> bool:
    return ((str(rec.get("county") or "").strip().lower() == "johnston")
            and (str(rec.get("state") or "").strip().upper() == "NC"))


def _dedupe_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply unmatched
        return None


def _existing_johnston_keys(docs: Path) -> set[str]:
    """Every dedupe_key() already on the board for an existing Johnston NC row -- found by
    streaming the WHOLE board exactly once (board_stream.iter_board_rows(), read-only, no
    lazy-detail sidecar), never load_board().

    The result SET is scoped to Johnston NC rows, but the stream itself still has to pass over
    every row in the board to find them -- that is not an approximation, just the cost of a
    single linear read. The scoping of the set is safe because every dedupe_key() a crosswalk
    Listing can produce takes the parcel branch (to_listing() always sets parcel_id to the
    resolved PIN) and that branch's key is "parcel:<state>:<county>:<pin>" -- county-scoped by
    construction (see Listing.dedupe_key() in models.py) -- so a crosswalk lead can only ever
    collide with an existing JOHNSTON NC row, never any other county's or state's.
    """
    keys: set[str] = set()
    for rec in iter_board_rows(docs / "listings.json.gz"):
        if not _is_johnston_nc(rec):
            continue
        key = _dedupe_key(rec)
        if key is not None:
            keys.add(key)
    return keys


def _classify(new_rows: list[Listing], existing_keys: set[str]) -> tuple[dict, list, int]:
    """Splits the scraper's resolved Listings into (patches, appends, self_collisions) by exact
    dedupe_key() match against `existing_keys`.

    `patches` maps dedupe_key() -> {"raw": {RAW_KEY: <this lead's tax-lien block>}} -- the same
    minimal, additive shape scripts/resolver_backfill_parcel.py uses (only the field(s) this
    producer actually resolves; nothing else on the existing row is touched).

    Two resolved leads sharing the SAME dedupe_key() (two different legacy parcels crosswalking
    to the same modern PIN -- not expected given aggregate_by_parcel()'s one-row-per-legacy-
    parcel grouping, but not impossible if the county's own roll carries a split/merged parcel
    under two legacy ids) is handled by keeping the first and counting the rest as
    `self_collisions`, surfaced in the CLI output rather than silently dropped -- the same
    "never silent" discipline patch_existing_rows()'s own duplicate_key_matches counter uses.
    """
    by_key: dict[str, list[Listing]] = {}
    unkeyed: list[Listing] = []
    for li in new_rows:
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001 - a lead too malformed to key is simply appended as-is
            unkeyed.append(li)
            continue
        by_key.setdefault(key, []).append(li)

    patches: dict[str, dict] = {}
    appends: list[Listing] = list(unkeyed)
    self_collisions = 0
    for key, group in by_key.items():
        if len(group) > 1:
            self_collisions += len(group) - 1
        li = group[0]
        if key in existing_keys:
            raw_block = li.raw.get(RAW_KEY) if isinstance(li.raw, dict) else None
            patch: dict = {}
            if raw_block is not None:
                patch["raw"] = {RAW_KEY: raw_block}
            if patch:
                patches[key] = patch
        else:
            appends.append(li)
    return patches, appends, self_collisions


async def _fetch_new() -> list:
    s = JohnstonDelinquentTaxCrosswalk()
    rows = list(await s.safe_run())
    print(f"scraper outcome: {s.last_outcome}; run_stats: {s.run_stats}")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_rows = asyncio.run(_fetch_new())
    print(f"scraped: {len(new_rows):,} rows "
          f"({sum(1 for r in new_rows if r.parcel_id):,} with a resolved parcel)")
    if not new_rows:
        print("nothing scraped — aborting.")
        return 1

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="johnston_tax_crosswalk_ingest")
    with lock:
        existing_keys = _existing_johnston_keys(docs)
        print(f"existing Johnston NC dedupe_keys on board: {len(existing_keys):,}")

        patches, appends, self_collisions = _classify(new_rows, existing_keys)
        print(f"\nclassified {len(new_rows):,} resolved leads:")
        print(f"  merge into an EXISTING board row (patch): {len(patches):,}")
        print(f"  genuinely NEW board rows (append):        {len(appends):,}")
        if self_collisions:
            print(f"  same-run PIN collisions (kept first, dropped): {self_collisions:,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            print(f"would patch_existing_rows() on {len(patches):,} existing rows")
            print(f"would append_new_rows() {len(appends):,} new rows")
            if patches:
                sample_key = next(iter(patches))
                print(f"  e.g. patch key: {sample_key}")
            if appends:
                sample = appends[0]
                print(f"  e.g. append: {sample.county} {sample.state} pin={sample.parcel_id} "
                      f"addr={sample.street_address}")
            return 0

        if patches:
            pstats = patch_existing_rows(
                patches, {"johnston_tax_crosswalk_ingest_patch": len(patches)}, docs_dir=docs)
            print(f"\npatch_existing_rows: {pstats}")
        else:
            print("\nnothing to patch (0 leads matched an existing row this run)")

        if appends:
            astats = append_new_rows(
                appends, {"johnston_tax_crosswalk_ingest_append": len(appends)}, docs_dir=docs)
            print(f"append_new_rows: {astats}")
        else:
            print("nothing to append (0 genuinely new leads this run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
