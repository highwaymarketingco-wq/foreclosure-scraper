#!/usr/bin/env python3
"""Join Williamsburg SC's already-built WTH tgis parcel cache onto the board's own
assessed_value/acreage (the `lot_size` cube column) fields -- round-17-misc
small-columns survey, 2026-11-17.

WHY THIS EXISTS. gap_matrix's 2026-11-16 gap list still flags Williamsburg SC "no
source known" for assessed_value (2,956 rows, 4.7% filled) and lot_size (2,956
rows, 23.34% filled). But `data/parcel_cache/williamsburg.sqlite`
(scripts/ingest_williamsburg_wthgis_parcels.py, built 2026-10-20) already carries
market_value for 3,347/3,347 cached parcels and acreage for 3,341/3,347 -- i.e.
the SOURCE is essentially 100% populated already. The gap is entirely downstream:
nothing has ever joined that cache onto these board rows' OWN assessed_value/
acreage fields at the backlog scale (the generic scripts/join_parcel_cache_to_board.py
would do this, but it calls load_board() -- refused here per this project's own
"never load_board()" rule; see feedback_load_board_scale_blowup_2026-10-22).
Separately, parcel_cache.lookup()'s own CACHE_VALUE_MAX_AGE_DAYS=10.0 staleness
guard already drops market_value/tax_value from ANY lookup against a cache this
old (28 days as of today) -- so a plain lookup() against the existing sqlite file
would silently omit the one field this backfill exists to fill. Rather than read a
guard-blocked stale cache, this script just RE-RUNS the existing, already-proven
ingest script's own live fetch (ingest_williamsburg_wthgis_parcels._run()) to get
a FRESH set of (record, board_parcel_ids) tuples in memory, writes the refreshed
sqlite cache from them (same as that script's own --apply path, now with today's
mtime, clearing the staleness guard for any other future consumer too), and THEN
joins those same in-memory records straight onto the board -- one live fetch,
two consumers, no second network pass.

FILL-ONLY, same discipline as backfill_orangeburg_assessed_value.py /
backfill_fl_co_deed_ref.py: never overwrites a value the board row already has.

BOARD I/O: one streaming read-only pass (board_stream.iter_board_rows(), inside
ingest_williamsburg_wthgis_parcels._board_williamsburg_rows()) to build the
candidate set; board_lock() wraps ONLY the final patch_existing_rows() write.
Never load_board().

    .venv/bin/python3 -I scripts/backfill_williamsburg_wthgis_board.py             # dry run
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python3 -I scripts/backfill_williamsburg_wthgis_board.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLockBusy, board_lock, board_patch_size_state, patch_existing_rows,
)
import ingest_williamsburg_wthgis_parcels as wb  # noqa: E402

STATE, COUNTY = "SC", "Williamsburg"
_LIGHT_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                  "case_number", "source_url", "listing_type", "source",
                  "owner_name", "defendant", "raw", "assessed_value", "acreage")


def _num(s) -> Optional[float]:
    try:
        v = float(str(s).strip())
    except (TypeError, ValueError, AttributeError):
        return None
    return v if v != 0 else None


def _board_index() -> dict[str, dict]:
    """{parcel_id -> raw board rec} for every existing Williamsburg SC row."""
    out = {}
    for rec in iter_board_rows(REPO / "docs" / "listings.json.gz"):
        if (rec.get("county") or "").strip().lower() == COUNTY.lower() and \
           (rec.get("state") or "").strip().upper() == STATE:
            pid = (rec.get("parcel_id") or "").strip()
            if pid:
                out[pid] = rec
    return out


def build_patches(records: list[tuple[dict, list[str]]], by_pid: dict[str, dict]
                   ) -> tuple[dict[str, dict], dict]:
    patches: dict[str, dict] = {}
    stats = {"no_board_match": 0, "no_key": 0, "no_new_data": 0}
    for rec, board_pids in records:
        mv = _num(rec.get("MarketValueTotalValue"))
        ac = _num(rec.get("MarketValueAcres"))
        if mv is None and ac is None:
            continue
        for pid in board_pids:
            r = by_pid.get(pid) or by_pid.get(wb._base_mapno(pid))  # noqa: SLF001
            if not r:
                stats["no_board_match"] += 1
                continue
            try:
                li = Listing.model_construct(**{f: r.get(f) for f in _LIGHT_FIELDS})
                key = li.dedupe_key()
            except Exception:  # noqa: BLE001
                stats["no_key"] += 1
                continue
            patch: dict = {}
            if mv is not None and not (r.get("assessed_value") or 0):
                patch["assessed_value"] = mv
            if ac is not None and not (r.get("acreage") or 0):
                patch["acreage"] = ac
            if patch:
                patches[key] = patch
            else:
                stats["no_new_data"] += 1
    return patches, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="cap board rows (canary run)")
    ap.add_argument("--apply", action="store_true", help="write patches (default: dry run)")
    args = ap.parse_args()

    result = asyncio.run(wb._run(args.limit))  # noqa: SLF001
    records = result["records"]
    print(f"fresh WTH fetch: {len(records):,} parcel detail records")
    if records:
        db_path = wb._write_cache(records)  # noqa: SLF001
        print(f"refreshed parcel_cache -> {db_path} ({db_path.stat().st_size/1e3:.0f} KB)")

    by_pid = _board_index()
    print(f"board index: {len(by_pid):,} Williamsburg SC rows with a parcel_id")

    patches, stats = build_patches(records, by_pid)
    print(f"\nboard patch candidates: {len(patches):,}  (stats: {stats})")

    if not patches:
        print("nothing to patch.")
        return 0
    if not args.apply:
        print("DRY RUN -- nothing written. Pass --apply to write for real.")
        for key, p in list(patches.items())[:5]:
            print("  ", key, p)
        return 0

    docs_dir = REPO / "docs"
    size_state = board_patch_size_state(docs_dir)
    if not size_state["ok"] and os.environ.get("BOARD_PATCH_ALLOW_LARGE") != "1":
        print(f"REFUSING: {size_state['reason']}. Set BOARD_PATCH_ALLOW_LARGE=1 to override.")
        return 1

    try:
        with board_lock(REPO, owner="backfill_williamsburg_wthgis_board", wait=3600, poll=10):
            pstats = patch_existing_rows(
                patches, {"backfill_williamsburg_wthgis_board": len(patches)}, docs_dir=docs_dir)
    except BoardLockBusy as exc:
        print(f"{exc} -- refusing to write ({len(patches):,} patches lost; re-run to redo).")
        return 1
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
