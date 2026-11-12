#!/usr/bin/env python3
"""One-off backfill: apply Horry SC's vacant_lot DOR-code-to-improvement-value
fallback (commit cea3d219, 2026-10-19 -- enrichment_vacant_landuse.py's
`improvement_value` branch) to Horry board rows that were published BEFORE
`parcel_cache.py`'s Horry cache was refreshed with the new `improvement_value`
column populated.

WHY THIS EXISTS
    Horry's parcel layer stores land_use as a 167-value numeric DOR code with
    no published legend anywhere (checked the county site, SC DOR, ArcGIS
    field domains, a national parcel reseller -- see
    project_gap_matrix_followups2_2026-10-19.md). cea3d219 added
    `improvement_value` (the layer's `MarketImprv` field) to parcel_cache's
    schema and a generic fallback in enrich_vacant_landuse(): a numeric
    land_use with a real improvement_value of exactly 0.0 (and some other
    signal -- market_value or acreage -- present, so this is not a blank row)
    is treated the same as a text "VACANT" land_use. The fallback only
    self-activates once `improvement_value` is actually populated in the
    cache file; Horry board rows scraped/enriched before that refresh never
    got a chance to match it. This script re-runs that one fallback branch
    against every current Horry board row, purely from the (now-refreshed)
    local cache -- zero network, zero rate-limit exposure.

SCOPE (bounded, not a full enrichment re-run)
    Horry, SC rows only. Only the improvement_value fallback branch is
    replicated here (mirrors enrich_vacant_landuse() in
    src/foreclosure_scraper/enrichment_vacant_landuse.py exactly -- not
    reimplemented independently): a numeric land_use, not already carrying
    raw.vacant_lot, with improvement_value present and (market_value or
    acreage) present. Text-land_use rows (the VACANT/VAC wordlist branch) are
    already covered by the existing full-board enrichment pass and are left
    alone here.

PREREQUISITE, checked at startup: parcel_cache's Horry db must actually have
    the `improvement_value` column AND it must be non-trivially populated.
    This script refuses (prints a clear message, exits 1) rather than running
    a no-op pass if the cache has not actually been refreshed yet on the host
    it is run on -- the Mac and the Oracle VM each keep their OWN local
    parcel_cache file (same cross-host-staleness hazard as the board itself;
    see project_board_regression_incident_2026-10-19.md), so "the fix is
    live" on one host does not mean it is live on the other.

BOARD I/O: board_stream.iter_board_rows() (read-only streaming scan) +
    web_artifact.patch_existing_rows() (dedupe_key()-keyed, same collision
    guard as backfill_anderson_situs_value.py / backfill_gaston_sqft_valtot.py)
    -- never load_board()/write_artifact() on this board size.

    .venv/bin/python scripts/backfill_horry_vacant_lot.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python scripts/backfill_horry_vacant_lot.py

2026-10-19 dry-run result (Oracle VM, post-cache-refresh, board @ 447,004
rows mid Wake-backfill -- read-only, no lock taken, safe to run concurrently):
6,639 Horry rows total; 3,498 numeric-DOR-code eligible; 5 no determinate
reading; **1,001 rows would newly get vacant_lot=True**; 2,492 confirmed
improved (checked, not vacant). Real write NOT applied this session --
Wake's backfill held the board at the time, and a board publish needs the
same explicit go-ahead as every other write tonight.
"""
from __future__ import annotations

import argparse
import contextlib
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import parcel_cache  # noqa: E402
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

#: Same identity fields web_artifact._APPEND_SIG_FIELDS keys patches on.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")

_COUNTY = "Horry"
_STATE = "SC"


def _dedupe_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def _check_cache_prereq() -> int:
    """Refuse to run a no-op pass against a cache that was never actually
    refreshed on THIS host. Returns the populated-row count (0 if absent)."""
    db_path = parcel_cache._db_path(_COUNTY, _STATE)  # noqa: SLF001
    if not db_path.exists():
        print(f"REFUSING: no parcel_cache db for {_COUNTY},{_STATE} at {db_path}")
        return -1
    import sqlite3
    con = sqlite3.connect(str(db_path))
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(parcels)")]
        if "improvement_value" not in cols:
            print(f"REFUSING: {db_path} has no improvement_value column yet -- "
                  f"this host's cache was not refreshed after cea3d219. Run "
                  f"parcel_cache.refresh_county('{_COUNTY}', '{_STATE}') first, "
                  f"or run this script on the host that already has.")
            return -1
        (populated,) = con.execute(
            "SELECT COUNT(*) FROM parcels WHERE improvement_value IS NOT NULL").fetchone()
        return populated
    finally:
        con.close()


def _collect_candidates(docs: Path):
    """ONE streaming pass over the whole board: tally every row's dedupe_key()
    (collision guard) and collect Horry SC candidates eligible for the
    improvement_value fallback, along with the cache lookup that would drive
    the patch -- so the reported breakdown and the patches dict are built
    from the exact same snapshot."""
    key_counts: Counter = Counter()
    candidates: list[tuple[str, str, dict]] = []  # (key, parcel_id, cache_rec)
    stats: Counter = Counter()
    scanned = horry_total = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        scanned += 1
        key = _dedupe_key(rec)
        if key is None:
            continue
        key_counts[key] += 1
        if (rec.get("county") or "").strip() != _COUNTY:
            continue
        if (rec.get("state") or _STATE) != _STATE:
            continue
        horry_total += 1
        raw = rec.get("raw") or {}
        if raw.get("vacant_lot"):
            stats["already_stamped"] += 1
            continue
        pid = (rec.get("parcel_id") or "").strip()
        if not pid:
            stats["no_parcel_id"] += 1
            continue
        cache_rec = parcel_cache.lookup(_COUNTY, pid, _STATE)
        lu = (cache_rec or {}).get("land_use")
        if not lu:
            stats["no_cache_hit"] += 1
            continue
        lu_s = str(lu).strip()
        if not lu_s.isdigit():
            stats["text_land_use_not_this_branch"] += 1
            continue
        stats["numeric_eligible"] += 1
        candidates.append((key, pid, cache_rec))
    return scanned, horry_total, key_counts, stats, candidates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="Cap candidates (testing)")
    args = ap.parse_args()

    populated = _check_cache_prereq()
    if populated <= 0:
        return 1
    print(f"parcel_cache improvement_value populated rows: {populated:,}")

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="backfill_horry_vacant_lot")

    with lock:
        print(f"[{time.strftime('%H:%M:%S')}] scanning board for Horry SC "
              f"candidates...", flush=True)
        scanned, horry_total, key_counts, stats, candidates = _collect_candidates(docs)
        print(f"scanned {scanned:,} board rows")
        print(f"Horry SC rows: {horry_total:,}")
        for k in ("already_stamped", "no_parcel_id", "no_cache_hit",
                  "text_land_use_not_this_branch", "numeric_eligible"):
            print(f"  {stats.get(k, 0):7,d}  {k}")

        if args.limit:
            candidates = candidates[:args.limit]

        deduped: list[tuple[str, str, dict]] = []
        collisions = 0
        for key, pid, cache_rec in candidates:
            if key_counts[key] > 1:
                collisions += 1
                continue
            deduped.append((key, pid, cache_rec))
        candidates = deduped
        print(f"  after dedupe_key() collision guard: {len(candidates):,} "
              f"eligible ({collisions:,} dropped as key collisions)")

        now_iso = datetime.now(timezone.utc).isoformat()
        patches: dict[str, dict] = {}
        match_stats: Counter = Counter()
        for key, pid, cache_rec in candidates:
            lu_s = str(cache_rec.get("land_use")).strip()
            imprv = cache_rec.get("improvement_value")
            has_other_signal = cache_rec.get("market_value") or cache_rec.get("acreage")
            if imprv is None or not has_other_signal:
                match_stats["no_determinate_reading"] += 1
                continue
            if float(imprv) != 0.0:
                match_stats["confirmed_improved"] += 1
                continue
            patches[key] = {
                "raw": {
                    "vacant_lot": {
                        "land_use": lu_s[:60],
                        "improvement_value": 0,
                        "source": "parcel_cache_improvement_value",
                    },
                    "horry_vacant_lot_backfill": {
                        "ts": now_iso, "parcel_id": pid,
                        "market_value": cache_rec.get("market_value"),
                        "acreage": cache_rec.get("acreage"),
                    },
                }
            }
            match_stats["newly_vacant"] += 1

        print("\n=== match stats ===")
        for k, v in sorted(match_stats.items()):
            print(f"  {v:7,d}  {k}")
        print(f"\ntotal patches ready: {len(patches):,}  "
              f"(== {match_stats['newly_vacant']:,} from match stats, must match)")
        assert len(patches) == match_stats["newly_vacant"], (
            "patches dict size diverged from the matched counter -- "
            "investigate before trusting either number")

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
            return 0

        result = patch_existing_rows(
            patches, {"backfill_horry_vacant_lot": f"{len(patches)} rows"},
            docs_dir=docs)
        print("\n=== patch_existing_rows result ===")
        for k, v in result.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
