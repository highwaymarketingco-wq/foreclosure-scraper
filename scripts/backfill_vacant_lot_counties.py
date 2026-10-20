#!/usr/bin/env python3
"""General county-parameterized backfill for the `vacant_lot` land-use/
improvement-value signal (enrichment_vacant_landuse.py), extending the exact
pattern proven and shipped for Horry SC (commit 0093e6f0,
scripts/backfill_horry_vacant_lot.py).

WHY A SEPARATE GENERALIZED SCRIPT RATHER THAN A ONE-OFF PER COUNTY
    2026-10-19's gap-matrix sweep found several more SC counties where
    `vacant_lot` is "sourced-not-built": a county parcel layer already
    cached (or cacheable) in parcel_cache.py simply never had the right
    land_use/improvement_value column mapped, or (Beaufort) had the right
    mapping all along but the board was never re-enriched after the cache
    was last refreshed with real land_use text. Rather than re-implementing
    enrich_vacant_landuse()'s branch logic per county (the drift risk the
    Horry script's own docstring calls out), this script calls the REAL
    enrichment function (foreclosure_scraper.enrichment_vacant_landuse.
    enrich_vacant_landuse) against lightweight, unvalidated Listing stand-ins
    built straight from board rows -- so a dry-run here is not a simulation
    of the production path, it IS the production path, run read-only.

COUNTIES COVERED THIS ROUND (2026-10-19 vacant_lot extension sweep)
    Colleton, SC  -- NEW land_use mapping (PropertyClass, direct text match,
                     e.g. "VACANT RESIDENTIAL"/"VACANT AGRICULTURAL"). No
                     improvement_value needed.
    Barnwell, SC  -- NEW improvement_value mapping (Tot_Market_Bldgs) added
                     alongside the land_use (PT163_Class, a bare-digit SC
                     4%/6% ratio-class code, not itself a vacant flag) that
                     was already mapped but inert with no value field to
                     pair it with.
    Beaufort, SC  -- NO parcel_cache.py change. land_use (GisFile_ClassCode)
                     was already mapped and the cache already carries real
                     ResVac/MHVac/HOAVac/TCUVac/AgVac text -- the board
                     simply predates that cache content. This is a pure
                     recompute, same shape as the other two but with zero
                     schema change. NOTE: only ~1.4% of Beaufort SC board
                     rows carry a parcel_id at all (25/1744, live-measured)
                     -- the real ceiling on this county is parcel_id
                     coverage, a separate and much larger gap outside this
                     script's scope.

Both Colleton and Barnwell's local parcel_cache files were refreshed live
this session (34,407/34,407 and 16,771/16,771 parcels respectively,
count-verified complete) before this script was written, so the mappings
below are backed by real cached data, not a hypothetical.

BOARD I/O: board_stream.iter_board_rows() (read-only streaming scan) +
    web_artifact.patch_existing_rows() (dedupe_key()-keyed collision guard),
    same convention as every other backfill script this project uses on this
    board size -- never load_board()/write_artifact().

    .venv/bin/python scripts/backfill_vacant_lot_counties.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python scripts/backfill_vacant_lot_counties.py
    # or a subset:
    .venv/bin/python scripts/backfill_vacant_lot_counties.py --dry-run --counties Colleton,SC Barnwell,SC
"""
from __future__ import annotations

import argparse
import contextlib
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import parcel_cache  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_vacant_landuse import (  # noqa: E402
    _VALUE_ONLY_NO_LANDUSE, enrich_vacant_landuse)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")

#: (county, state) pairs this round. Extend this tuple, not the logic, for
#: the next county the gap-matrix sweep clears.
DEFAULT_TARGETS: tuple[tuple[str, str], ...] = (
    ("Colleton", "SC"),
    ("Barnwell", "SC"),
    ("Beaufort", "SC"),
    # 2026-10-20 round: Sumter SC, the enrichment_vacant_landuse._VALUE_ONLY_NO_LANDUSE
    # county -- its cache has NO land_use field at all, so _check_cache_prereq below checks
    # improvement_value populated for it instead of land_use (see that function's own note).
    ("Sumter", "SC"),
)


def _dedupe_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def _check_cache_prereq(targets) -> dict[tuple[str, str], int]:
    """Refuse targets whose cache on THIS host has no data for the field(s)
    this round's mapping needs -- same discipline as the Horry script's
    _check_cache_prereq, generalized to "land_use populated at all".

    A county on enrichment_vacant_landuse._VALUE_ONLY_NO_LANDUSE (Sumter: the layer has no
    land_use field of any kind, see that set's own docstring) is checked against
    improvement_value instead -- the field its whole signal actually comes from there."""
    import sqlite3
    ok: dict[tuple[str, str], int] = {}
    for county, state in targets:
        db_path = parcel_cache._db_path(county, state)  # noqa: SLF001
        if not db_path.exists():
            print(f"REFUSING {county},{state}: no parcel_cache db at {db_path}")
            continue
        value_only = county in _VALUE_ONLY_NO_LANDUSE
        check_col = "improvement_value" if value_only else "land_use"
        con = sqlite3.connect(str(db_path))
        try:
            cols = [r[1] for r in con.execute("PRAGMA table_info(parcels)")]
            if check_col not in cols:
                print(f"REFUSING {county},{state}: cache schema has no {check_col} column "
                      f"(very old cache file -- refresh it first)")
                continue
            if value_only:
                (populated,) = con.execute(
                    "SELECT COUNT(*) FROM parcels WHERE improvement_value IS NOT NULL").fetchone()
            else:
                (populated,) = con.execute(
                    "SELECT COUNT(*) FROM parcels WHERE land_use IS NOT NULL "
                    "AND land_use != ''").fetchone()
            if populated == 0:
                print(f"REFUSING {county},{state}: {check_col} column exists but is "
                      f"100% empty on this host's cache -- refresh it first")
                continue
            ok[(county, state)] = populated
        finally:
            con.close()
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--counties", nargs="*", metavar="County,ST",
                     help="e.g. Colleton,SC Barnwell,SC (default: all of DEFAULT_TARGETS)")
    ap.add_argument("--limit", type=int, default=None, help="Cap patches (testing)")
    args = ap.parse_args()

    if args.counties:
        targets = []
        for spec in args.counties:
            name, _, st = spec.partition(",")
            targets.append((name.strip(), st.strip().upper()))
    else:
        targets = list(DEFAULT_TARGETS)

    cache_ok = _check_cache_prereq(targets)
    if not cache_ok:
        print("No targets with a usable, populated cache. Nothing to do.")
        return 1
    for (c, s), n in cache_ok.items():
        print(f"parcel_cache land_use populated rows for {c},{s}: {n:,}")
    target_set = set(cache_ok.keys())

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="backfill_vacant_lot_counties")

    with lock:
        print(f"\n[{time.strftime('%H:%M:%S')}] scanning board...", flush=True)
        key_counts: Counter = Counter()
        # one Listing stand-in per eligible row, grouped by (county, state) for reporting
        by_county: dict[tuple[str, str], list] = {t: [] for t in target_set}
        row_meta: dict[int, tuple[str, dict]] = {}  # id(listing) -> (dedupe_key, original raw)
        county_totals: Counter = Counter()
        scanned = 0

        for rec in iter_board_rows(docs / "listings.json.gz"):
            scanned += 1
            key = _dedupe_key(rec)
            if key is not None:
                key_counts[key] += 1
            county = (rec.get("county") or "").strip()
            state = (rec.get("state") or "").strip().upper()
            tkey = (county, state)
            if tkey not in target_set or key is None:
                continue
            county_totals[tkey] += 1
            raw = rec.get("raw") or {}
            if raw.get("vacant_lot"):
                continue
            pid = (rec.get("parcel_id") or "").strip()
            if not pid:
                continue
            li = Listing.model_construct(
                parcel_id=pid, county=county, state=state,
                address=rec.get("address") or "",
                source=rec.get("source") or "board", source_url=rec.get("source_url") or "",
                raw=dict(raw), land_use=rec.get("land_use"))
            by_county[tkey].append(li)
            row_meta[id(li)] = (key, raw)

        print(f"scanned {scanned:,} board rows")
        total_eligible = sum(len(v) for v in by_county.values())
        print(f"rows with parcel_id, not already stamped, in target counties: {total_eligible:,}")
        for tkey in target_set:
            print(f"  {tkey[0]},{tkey[1]}: applicable={county_totals[tkey]:,} "
                  f"eligible_for_enrich={len(by_county[tkey]):,}")

        all_listings = [li for v in by_county.values() for li in v]
        print(f"\nrunning the real enrich_vacant_landuse() against {len(all_listings):,} "
              f"candidate rows...")
        stats = enrich_vacant_landuse(all_listings)
        print(f"enrich_vacant_landuse stats: {dict(stats)}")

        patches: dict[str, dict] = {}
        per_county_newly: Counter = Counter()
        collisions = 0
        for tkey, listings in by_county.items():
            for li in listings:
                key, orig_raw = row_meta[id(li)]
                if not li.raw.get("vacant_lot"):
                    continue  # enrichment looked, found this one genuinely improved (or indeterminate)
                if key_counts[key] > 1:
                    collisions += 1
                    continue
                if args.limit and len(patches) >= args.limit:
                    continue
                patch_raw = {"vacant_lot": li.raw["vacant_lot"]}
                # land_use_filled: enrich_vacant_landuse also backfills Listing.land_use
                # in place (not in raw) when the row had none; patch_existing_rows only
                # touches `raw`, so that specific side effect is intentionally NOT
                # replicated here -- matches the Horry script's scope (raw.vacant_lot only).
                patches[key] = {"raw": patch_raw}
                per_county_newly[tkey] += 1

        print("\n=== newly-vacant_lot by county ===")
        for tkey in target_set:
            print(f"  {tkey[0]},{tkey[1]}: {per_county_newly.get(tkey, 0):,}")
        print(f"\ncollisions dropped (dedupe_key shared with another board row): {collisions:,}")
        print(f"total patches ready: {len(patches):,}")

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
            return 0

        result = patch_existing_rows(
            patches,
            {"backfill_vacant_lot_counties": f"{len(patches)} rows across "
             f"{len(target_set)} counties"},
            docs_dir=docs)
        print("\n=== patch_existing_rows result ===")
        for k, v in result.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
