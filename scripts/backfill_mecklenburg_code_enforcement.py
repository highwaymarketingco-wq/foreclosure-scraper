#!/usr/bin/env python3
"""Mecklenburg NC 'code_enforcement' catch-up for Charlotte-city rows: run the REAL,
unmodified enrich_with_code_enforcement() (src/foreclosure_scraper/enrichment_code_
enforcement.py) over every Charlotte-city Mecklenburg board row that has never been
screened, in bounded, checkpointed batches.

WHY THIS EXISTS (gap-matrix follow-up, 2026-11-10, "code_enforcement" built-but-low-yield)
    gap_matrix.py's SPECS["code_enforcement"] producers tuple names "enrichment_charlotte_
    code.py" as a Mecklenburg producer. Read that file directly: its own docstring says
    "RETIRED 2026-10-09 ... main.py does not run this module and nothing should" -- it is
    dead code, three speculative 403-bypass strategies against endpoints that were never the
    real one. The REAL, LIVE Mecklenburg producer is enrichment_code_enforcement.py's own
    CITY_ENDPOINTS["Charlotte"] entry (gis.charlottenc.gov's CodeEnforcementNewAndOpenCases
    layer, 3,966 features verified live 2026-09-10) plus SEVERE_ENDPOINTS["Charlotte"]
    (CodeEnforcementOrderstoDemolish, wired as a second pass 2026-10-29) -- a completely
    different, working module the stale SPECS entry does not even list. (A THIRD, separate
    mechanism, city_websites/charlotte_open_data.py's CodeEnforcementCasesAll layer, is a
    SOURCE that creates new board rows from the live feed, not a per-existing-row enricher;
    out of scope here, see backfill_mecklenburg_vacancy_fof.py for the one piece of it -- the
    FOFOrdered/vacancy flag -- this round reuses.)

    enrich_with_code_enforcement() already has a correct negative-write path
    (_clear_stale_block, fixed 2026-10-16) and was already run at scale once (2026-10-29,
    14 cities incl. Charlotte, 20,000-row shared budget, 18,819 applied) -- but that budget
    was split across 14 cities, not scoped to Mecklenburg. Measured 2026-11-10: of
    Mecklenburg's 39,861 rows, 30,580 have city=="Charlotte" (the ONLY city this module's
    CITY_ENDPOINTS/SEVERE_ENDPOINTS dicts key on for Mecklenburg); 17,277 of those 30,580
    have NEVER been screened by this producer (raw['code_enforcement'] missing or {}). The
    other 9,256 never-checked Mecklenburg rows (39,861 - 30,580 city==Charlotte, roughly --
    Huntersville/Matthews/Cornelius/Mint Hill/Pineville/Davidson/blank-city) have NO
    mechanism wired via CITY_ENDPOINTS at all (only "Charlotte" is a key); charlotte_open_
    data.py's county-wide CasesAll feed is the only lead for those, and it is a source, not
    an enricher -- a separate, NOT-attempted-here follow-up (it cannot write a negative
    "no case" stamp for a row it never produces).

THIS IS A LIVE, PER-ROW NETWORK CALL, NOT A CHEAP OFFLINE PASS. Each row costs one ArcGIS
query against gis.charlottenc.gov per pass (CITY_ENDPOINTS, then SEVERE_ENDPOINTS -- enrich_
with_code_enforcement() runs both internally per call), serialized by http_client.py's
shared per-hostname throttle (~0.8-1.5s/request regardless of this module's own
asyncio.Semaphore(4)) -- the 2026-10-29 run measured ~1.17s/row averaged across both passes
and 14 cities. At that pace the 17,277-row Charlotte backlog is roughly 5.5-6 hours of
wall-clock time for ONE full sweep -- this script batches it (--batch-size, default 1500,
~1,500 rows * ~1.17s ~= 29 min/batch) and checkpoints a patch after every batch, so a single
invocation can be bounded (--max-batches) and progress already made survives an interruption
or a later invocation picking up where this one left off (never-checked-first selection,
same as every other backfill this round).

BOARD I/O: Pass 1 streams the whole board once (board_stream.iter_board_rows(), never
load_board()) to tally dedupe_key() collisions AND collect the Mecklenburg/Charlotte
candidate set as light Listing objects (only the 'code_enforcement' raw sub-key copied, the
same trimming discipline as scripts/backfill_bop_federal.py). Pass 2 runs the REAL enrich_
with_code_enforcement() against that (bounded, ~17K-row) candidate set in batches, diffing
raw['code_enforcement'] before/after each batch and patching via web_artifact.
patch_existing_rows() immediately (not held to the end).

    python scripts/backfill_mecklenburg_code_enforcement.py --dry-run
        # candidate-count only: NO live network calls, NO writes.
    python scripts/backfill_mecklenburg_code_enforcement.py --max-batches 1
        # one real ~1,500-row batch (orchestrating session only; needs the board lock).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_code_enforcement import (  # noqa: E402
    enrich_with_code_enforcement,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")
_LIGHT_FIELDS = _SIG_FIELDS + ("city", "latitude", "longitude", "source")
_TARGET_CITY = "Charlotte"


def _dedupe_key(rec: dict) -> Optional[str]:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Candidate-count only: no live network calls, no writes.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Stop scanning after this many board rows (testing)")
    ap.add_argument("--batch-size", type=int, default=1500,
                    help="Rows per live enrich_with_code_enforcement() call + checkpoint patch")
    ap.add_argument("--max-batches", type=int, default=None,
                    help="Stop after this many batches this invocation (omit = run to completion)")
    args = ap.parse_args()

    docs = REPO / "docs"

    print("pass 1/2: streaming the full board for dedupe-collision tally + "
          "Mecklenburg/Charlotte candidate selection...")
    key_counts: Counter = Counter()
    candidates: dict[str, Listing] = {}
    scanned = 0
    meck_total = 0
    meck_charlotte = 0
    already_checked = 0
    skipped_no_key = 0

    for rec in iter_board_rows(docs / "listings.json.gz"):
        scanned += 1
        key = _dedupe_key(rec)
        if key is None:
            skipped_no_key += 1
        else:
            key_counts[key] += 1

        st = (rec.get("state") or "").strip().upper()
        co = (rec.get("county") or "").strip()
        if st == "NC" and co == "Mecklenburg":
            meck_total += 1
            city = (rec.get("city") or "").strip().title()
            if city == _TARGET_CITY:
                meck_charlotte += 1
                raw = rec.get("raw") or {}
                ce = raw.get("code_enforcement")
                if ce is not None and ce != {}:
                    already_checked += 1
                elif key is not None:
                    li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
                    li.raw = {"code_enforcement": ce} if ce is not None else {}
                    candidates[key] = li
        if args.limit and scanned >= args.limit:
            break

    collision_keys = {k for k in candidates if key_counts[k] > 1}
    for k in collision_keys:
        del candidates[k]

    print(f"scanned {scanned:,} board rows")
    print(f"Mecklenburg rows: {meck_total:,} | city==Charlotte: {meck_charlotte:,}")
    print(f"  already screened (raw.code_enforcement present): {already_checked:,}")
    print(f"  dropped as dedupe_key collisions: {len(collision_keys):,} "
          f"(no dedupe key at all: {skipped_no_key:,})")
    print(f"NEVER-SCREENED Charlotte candidates this script can act on: {len(candidates):,}")

    n_batches = (len(candidates) + args.batch_size - 1) // args.batch_size if candidates else 0
    est_hours = len(candidates) * 1.17 * 2 / 3600  # both CITY_ENDPOINTS + SEVERE_ENDPOINTS passes
    print(f"  at --batch-size {args.batch_size}: {n_batches} batches; "
          f"est. ~{est_hours:.1f}h wall-clock for the full backlog at the "
          f"2026-10-29 run's measured ~1.17s/row/pass pace")

    if args.dry_run:
        print("\nDRY RUN -- no live network calls made, nothing written.")
        return 0
    if not candidates:
        print("\nnothing to do.")
        return 0

    items = list(candidates.items())
    batches_run = 0
    total_patched = 0
    total_new_positive = 0
    total_new_negative = 0
    total_unresolved = 0  # still None after the call: could not be asked (outage/no address)

    with board_lock(REPO, owner="backfill_mecklenburg_code_enforcement", wait=3600, poll=10):
        for i in range(0, len(items), args.batch_size):
            if args.max_batches and batches_run >= args.max_batches:
                print(f"\nreached --max-batches {args.max_batches}; stopping "
                      f"({len(items) - i:,} candidates remain for a future invocation).")
                break
            batch = dict(items[i:i + args.batch_size])
            before = {k: li.raw.get("code_enforcement") for k, li in batch.items()}

            t0 = time.monotonic()
            print(f"\n[batch {batches_run}] running enrich_with_code_enforcement() on "
                  f"{len(batch):,} Charlotte rows (CITY_ENDPOINTS + SEVERE_ENDPOINTS)...",
                  flush=True)
            asyncio.run(enrich_with_code_enforcement(list(batch.values())))
            elapsed = time.monotonic() - t0

            patches: dict[str, dict] = {}
            new_pos = new_neg = unresolved = 0
            for k, li in batch.items():
                after = li.raw.get("code_enforcement") if isinstance(li.raw, dict) else None
                if after == before[k]:
                    if after is None:
                        unresolved += 1
                    continue
                patches[k] = {"raw": {"code_enforcement": after}}
                if isinstance(after, dict) and after.get("has_open"):
                    new_pos += 1
                elif isinstance(after, dict):
                    new_neg += 1

            stats = patch_existing_rows(
                patches, {"backfill_mecklenburg_code_enforcement": f"batch={batches_run}"},
                docs_dir=docs) if patches else {"applied": 0, "not_found": 0,
                                                "duplicate_key_matches": 0, "existing": None}
            total_patched += stats["applied"]
            total_new_positive += new_pos
            total_new_negative += new_neg
            total_unresolved += unresolved
            batches_run += 1
            print(f"  [batch {batches_run - 1}] {elapsed:.0f}s | new open-violation tags: "
                  f"{new_pos} | newly cleared (checked, nothing found): {new_neg} | "
                  f"could not be asked (outage/no address): {unresolved} | "
                  f"patched: {stats['applied']}/{len(patches)} "
                  f"(not_found: {stats['not_found']}, "
                  f"duplicate_key_matches: {stats['duplicate_key_matches']})", flush=True)

    print(f"\n=== RESULTS ===")
    print(f"batches run: {batches_run}")
    print(f"rows patched: {total_patched:,}")
    print(f"  new open-violation tags (positive): {total_new_positive:,}")
    print(f"  newly cleared / checked-nothing-found (negative): {total_new_negative:,}")
    print(f"  could not be asked (outage/no address, left unstamped for retry): {total_unresolved:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
