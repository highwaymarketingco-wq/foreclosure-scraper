#!/usr/bin/env python3
"""Mecklenburg NC 'vacancy' catch-up: mark every Mecklenburg board row CHECKED against
Charlotte/Mecklenburg's live Findings-of-Fact (demolition-order) case list, not just the
rows that happen to already match one.

WHY THIS EXISTS (gap-matrix follow-up, 2026-11-10, "vacancy" built-but-low-yield cluster)
    gap_matrix.py's SPECS["vacancy"] producers tuple (hendersonville_vacant_structures.py,
    rocky_mount_blight_survey.py, kinston_proposed_demolition.py, gastonia_code_enforcement.py)
    is a GENERIC list that does not include Mecklenburg's real producer at all -- the same
    stale-producers-tuple bug class already fixed once for marriage_license (2026-10-16) and
    flagged again for code_enforcement's own "enrichment_charlotte_code.py" entry (retired,
    see backfill_mecklenburg_code_enforcement.py's docstring). The REAL mechanism for
    Mecklenburg is `city_websites/charlotte_open_data.py`'s 2026-10-20 fix: a case with
    FOFOrdered=1 (a county "Findings of Fact" demolition order -- the clearest "the owner has
    already been told to vacate this structure" signal there is) is stamped into
    raw['vacancy'] = {"vacant": True, ...} -- but ONLY as a side effect of that SOURCE
    producing a brand-new Listing row for a case it has not seen before. It has no way to
    revisit an EXISTING board row and no negative-write path at all (a source produces
    positive rows by construction; it never emits "this case does not exist"). Measured
    2026-11-10: of 39,861 Mecklenburg rows, only 15 carry raw['vacancy'] (the 16 FOFOrdered
    cases from the 2026-10-23 land_charlotte_open_data_refresh.py run, minus 1 that didn't
    dedupe-match); 29,044 have a parcel_id this backfill can join against; the other 10,817
    have no parcel_id and are NOT touched here (reported separately, never guessed at).

THIS IS NOT A PER-ROW LIVE LOOKUP. One bulk fetch (the SAME CharlotteOpenData().fetch(),
2-4 paginated ArcGIS calls for ~3,000-4,000 county-wide open cases) builds the full live
FOFOrdered parcel set ONCE; everything after that is a pure in-memory join against the
board, zero additional network calls per row. This is the "cheap, offline-shaped" backfill
distinguished from the live-per-row-request ones (code_enforcement, sos_dissolution).

SCOPE. Mecklenburg-county-wide, NOT Charlotte-city-only: the live service's FullAddress
values span Huntersville/Cornelius/Davidson/Matthews/Mint Hill/Pineville/Stallings too
(charlotte_open_data.py's own _MUNICIPALITIES list), because HNS (Housing & Neighborhood
Services) is a COUNTY department, unlike enrichment_code_enforcement.py's CITY_ENDPOINTS
entry, which is address-matched against Charlotte city limits specifically.

WRITE SEMANTICS (same "checked vs never-checked" contract as every other backfill in this
round): a row whose parcel_id does NOT appear in the live FOFOrdered set gets a NEGATIVE,
dated wrapper ({"vacant": False, ...}) -- this is the whole point, so the row reads
"checked, no demolition order on file" instead of "never checked" forever. Verified this is
scoring-safe by reading gap_matrix.py's _gate_vacancy() directly: it requires
`v.get("vacant") is True`, so a False-shaped dict can never be misread as a positive hit,
while checked_columns()'s `isinstance(raw.get("vacancy"), dict)` correctly counts it as
screened. A row whose parcel_id DOES appear gets the real positive wrapper, identical in
shape to charlotte_open_data.py's own write. Never overwrites an existing raw['vacancy'].

BOARD I/O: streamed via board_stream.iter_board_rows() (never load_board()), collision-
guarded via a whole-board dedupe_key() tally exactly like scripts/backfill_tax_aging_
surfaced.py, patched via web_artifact.patch_existing_rows() in checkpoints.

    python scripts/backfill_mecklenburg_vacancy_fof.py --dry-run
    python scripts/backfill_mecklenburg_vacancy_fof.py          # applies (orchestrating session only)
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.city_websites.charlotte_open_data import (  # noqa: E402
    CharlotteOpenData,
)
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")
_SOURCE_TAG = "charlotte_open_data_fof_backfill"
CHECKPOINT_EVERY = 20_000


def _dedupe_key(rec: dict) -> Optional[str]:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


async def _fetch_live_fof_parcels() -> tuple[set[str], int, int]:
    """The REAL, unmodified CharlotteOpenData scraper's fetch() -- same bulk ArcGIS query the
    normal scraping pipeline runs. Returns (fof_parcel_ids, total_open_cases, fof_case_count)."""
    listings = await CharlotteOpenData().fetch()
    fof_parcels: set[str] = set()
    fof_cases = 0
    for li in listings:
        if isinstance(li.raw, dict) and isinstance(li.raw.get("vacancy"), dict) \
                and li.raw["vacancy"].get("vacant") is True:
            fof_cases += 1
            if li.parcel_id:
                fof_parcels.add(li.parcel_id)
    return fof_parcels, len(listings), fof_cases


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="Stop after inspecting this many board rows (testing)")
    ap.add_argument("--state", default="NC")
    ap.add_argument("--county", default="Mecklenburg")
    args = ap.parse_args()

    docs = REPO / "docs"
    want_state = (args.state or "").strip().upper() or None
    want_county = (args.county or "").strip() or None

    print("fetching the live Charlotte/Mecklenburg open-case feed "
          "(CharlotteOpenData().fetch(), 2-4 paginated ArcGIS calls)...")
    fof_parcels, total_open, fof_case_count = asyncio.run(_fetch_live_fof_parcels())
    print(f"  {total_open:,} currently-open cases; {fof_case_count:,} carry an active "
          f"Findings-of-Fact demolition order; {len(fof_parcels):,} distinct parcels")

    # wait=3600/poll=10: board_lock()'s default (wait=0.0) raises BoardLockBusy immediately
    # instead of queuing behind a concurrently-running writer (confirmed live tonight -- the
    # board-wide gis_attrs backfill holds this lock for minutes at a time, routinely).
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="backfill_mecklenburg_vacancy_fof", wait=3600, poll=10)

    with lock:
        key_counts: Counter = Counter()
        patches: dict[str, dict] = {}
        patch_source: dict[str, str] = {}
        scanned = 0
        in_scope_rows = 0
        already_had_it = 0
        no_parcel = 0
        skipped_no_key = 0
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        for rec in iter_board_rows(docs / "listings.json.gz"):
            scanned += 1
            key = _dedupe_key(rec)
            if key is None:
                skipped_no_key += 1
            else:
                key_counts[key] += 1

            st = (rec.get("state") or "").strip().upper()
            co = (rec.get("county") or "").strip()
            if want_state and st != want_state:
                pass
            elif want_county and co != want_county:
                pass
            else:
                in_scope_rows += 1
                raw = rec.get("raw") or {}
                existing_vac = raw.get("vacancy")
                if isinstance(existing_vac, dict) and existing_vac:
                    already_had_it += 1
                elif key is None:
                    pass
                else:
                    parcel = (rec.get("parcel_id") or "").strip() or None
                    if not parcel:
                        no_parcel += 1
                        continue
                    if parcel in fof_parcels:
                        wrapper = {"vacant": True, "boarded_up": None, "utility_status": None,
                                   "source": _SOURCE_TAG, "checked_at": now}
                    else:
                        wrapper = {"vacant": False, "boarded_up": None, "utility_status": None,
                                   "source": _SOURCE_TAG, "checked_at": now}
                    patches[key] = {"raw": {"vacancy": wrapper}}
                    patch_source[key] = rec.get("source") or "?"
            if args.limit and scanned >= args.limit:
                break

        collision_keys = {k for k in patches if key_counts[k] > 1}
        for k in collision_keys:
            del patches[k]
            patch_source.pop(k, None)

        # Counted from the FINAL patches dict (post-collision-removal), by distinct dedupe_key
        # -- never from a per-row running tally, which would double-count a key visited by more
        # than one physical row before the collision filter above removes it.
        positive = sum(1 for p in patches.values() if p["raw"]["vacancy"]["vacant"] is True)
        negative = len(patches) - positive

        print(f"\nscanned {scanned:,} board rows | in-scope ({want_state or 'any'}/"
              f"{want_county or 'any'}): {in_scope_rows:,}")
        print(f"already carried raw.vacancy: {already_had_it:,}")
        print(f"no parcel_id (cannot join -- NOT touched, NOT claimed as checked): {no_parcel:,}")
        print(f"  dropped as dedupe_key collisions: {len(collision_keys):,} "
              f"(no dedupe key at all: {skipped_no_key:,})")
        print(f"  landable this run: {len(patches):,}  (positive: {positive:,}  "
              f"negative/checked-clean: {negative:,})")

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
            return 0

        items = list(patches.items())
        applied_total = 0
        for i in range(0, len(items), CHECKPOINT_EVERY):
            chunk = dict(items[i:i + CHECKPOINT_EVERY])
            stats = patch_existing_rows(
                chunk, {"backfill_mecklenburg_vacancy_fof": f"chunk={i}"}, docs_dir=docs)
            applied_total += stats["applied"]
            print(f"  [checkpoint {i}] patched {stats['applied']}/{len(chunk)} "
                  f"(existing board: {stats['existing']:,}, "
                  f"not_found: {stats['not_found']}, "
                  f"duplicate_key_matches: {stats['duplicate_key_matches']})", flush=True)

        print(f"\n=== RESULTS ===")
        print(f"rows scanned: {scanned:,}")
        print(f"rows patched: {applied_total:,}  (positive: {positive:,}, negative: {negative:,})")
        print(f"dropped as dedupe_key collisions: {len(collision_keys):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
