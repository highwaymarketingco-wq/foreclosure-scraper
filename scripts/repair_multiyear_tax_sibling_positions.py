#!/usr/bin/env python3
"""Revert multi_year_delinquent_tax/two_year_delinquent on exactly 30 known sibling-row
POSITIONS in docs/listings.json back to their state in the pre-write backup
backups/listings_20261019_040732.json.

WHY. scripts/backfill_multiyear_tax_restatement.py's real run (2026-10-19) reported 31
duplicate_key_matches. A full spot-check (streaming the live board and, separately, the
pre-write backup, by position) found that EVERY one of the 31 colliding dedupe_key groups has
exactly ONE row that genuinely carries its own qpaybill_roll source block -- every other row
under that key has NO source block of its own at all. The real question for each of the 31 is
therefore not "did my code misfire" (it didn't -- it correctly restated the one true
candidate's own data) but "does patch_existing_rows()'s shared-dedupe_key semantics correctly
apply to the sibling too" -- i.e. is the sibling genuinely the SAME taxable parcel, or an
unrelated thing that merely shares a parcel-number string.

Per-group disposition (see the task report this script accompanies for the full reasoning):

  REVERT (30 rows, 28 keys) -- sibling is NOT the same taxable item as the qpaybill-sourced row:
    * 26 SC Dillon County rows (24 keys; one key has 3 siblings) -- every single Dillon
      "sibling" is a counties_sc.dillon_delinquent_tax row whose street_address field is
      actually a MOBILE/MANUFACTURED HOME description (make, dimensions, serial number) with
      its own, DIFFERENT case_number from the land row's. Dillon's tax system bills a mobile
      home separately from the land it sits on, filed under the land parcel's TMS number for
      reference -- two separate tax bills sharing one parcel number is not "the same property."
    * Spartanburg parcel 7080400100 and 3290806600 -- both sides are produced by the SAME
      scraper (qpaybill_delinquent_roll) but the two addresses (e.g. "505 Lakewood Park Dr" vs
      "405 Larry Dr") have no textual relationship at all, unlike every KEPT case below. Most
      likely two different physical parcels that coincidentally collapsed to one dedupe_key in
      the source roll; too weak to trust.
    * Abbeville parcel 0009900005 -- the two rows do not even share the same raw parcel_id
      STRING ("000-99-00-005" vs "000-99-00-00-500"); they only coincidentally NORMALIZE to the
      same key, and one side's address carries a junk "XXXXXXXXXX" placeholder suffix.
    * Oconee parcel 1231101008 -- the sibling (oconee_forfeited_land, pos 427106) is a
      different-lifecycle record (post-forfeiture) with a fully different address FORMAT, and
      critically it already carried ITS OWN pre-existing two_year_delinquent (`{"is_two_year_
      plus": false, ..., "source": "default"}`) before this backfill ran -- the real write
      silently clobbered that distinct prior value via patch_existing_rows()'s unconditional
      raw.update(). That clobbered loss, not just a questionable share, is why this one is
      reverted rather than trusted.

  LEFT AS-IS (3 keys, 6 rows, not touched by this script) -- sibling IS plausibly the same
  taxable parcel:
    * Cherokee 117-00-00-001.005 -- identical parcel_id string; the sibling's own address
      ("995:997:999 River Dr") is a clean superset of the qpaybill row's ("999 River Dr"), no
      case_number conflict.
    * Marlboro 019-96-49-075 -- identical parcel_id string, SAME producer on both sides,
      adjacent addresses on the same road (a county-roll duplicate-entry quirk, not two
      different taxable items).
    * Spartanburg 7-15-08-292.01 -- identical parcel_id string, adjacent addresses on the same
      road (759 vs 755 John B White Sr Blvd), same shape as the two kept cases above despite a
      different producer (arcgis_distress.spartanburg_city_tax_sale).

MECHANICS mirror scripts/repair_deed_ref_bound_sibling_positions.py's write tail exactly
(board_lock, streamed read of listings.json by _iter_board_records, lazy-detail-key pop into
listings_detail.json, _count_guard_and_backup for a FRESH pre-this-write backup,
_write_plain_array, board_parts.write_parts, write_manifest) -- the revert logic itself is the
same simple position-keyed restore, just a different backup source and a different 2-key set.

USAGE
    .venv/bin/python scripts/repair_multiyear_tax_sibling_positions.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python scripts/repair_multiyear_tax_sibling_positions.py
"""
from __future__ import annotations

import gzip
import hashlib
import itertools
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import board_parts as _bp  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLockBusy, LAZY_DETAIL_KEYS, MANIFEST_NAME, _apply_health_freshness,
    _atomic_write_bytes, _check_not_changed_since_load, _count_guard_and_backup,
    _iter_board_records, _write_plain_array, board_lock, load_manifest,
    require_board_lock, write_manifest,
)

DOCS = REPO / "docs"
BACKUP = REPO / "backups" / "listings_20261019_040732.json"

#: 26 Dillon mobile-home-side positions (land side, carrying the real qpaybill_roll data,
#: is untouched) + 2 Spartanburg + 1 Abbeville + 1 Oconee = 30 positions total.
TARGET_POSITIONS = {
    # Dillon County mobile-home siblings (24 keys, one with 3 siblings)
    420348, 420468, 420040, 420089, 420091, 420321, 420207, 420085, 420616, 420174,
    420199, 420201, 420203, 420688, 420326, 420350, 420370, 420418, 420419, 420058,
    420187, 420522, 420525, 420478, 420053, 420184,
    # Spartanburg -- both sides qpaybill_delinquent_roll, unrelated addresses
    63835, 64707,
    # Abbeville -- different raw parcel_id strings, only coincidentally normalize together
    67197,
    # Oconee -- forfeited-land sibling whose own pre-existing value got clobbered
    427106,
}
assert len(TARGET_POSITIONS) == 30, f"expected 30 target positions, got {len(TARGET_POSITIONS)}"

KEYS = ("two_year_delinquent", "multi_year_delinquent_tax")


def _engine_running() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", "--",
         r"run_local\.sh|-m foreclosure_scraper|merge_today_sources|resolver_backfill|load_board|recompute_valuation|recompute_geo_imprecise|backfill_multiyear_tax_restatement"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if _engine_running():
        print("engine/backfill/another loader is running -- refusing to touch the board",
              file=sys.stderr)
        return 1

    t0 = time.time()
    lock = None
    if not args.dry_run:
        try:
            lock = board_lock(REPO, owner="revert_multiyear_tax_sibling_rows")
            lock.__enter__()
        except BoardLockBusy as exc:
            print(f"{exc} -- refusing to write.", file=sys.stderr)
            return 1

    try:
        return _run(args, t0)
    finally:
        if lock is not None:
            lock.__exit__(None, None, None)


def _run(args, t0) -> int:
    listings_path = DOCS / "listings.json"
    if not args.dry_run:
        require_board_lock(DOCS)
        _check_not_changed_since_load(listings_path)

    cur_iter = _iter_board_records(DOCS)          # sidecar merged, CURRENT board (has the bug)
    bak_iter = _bp.iter_plain_rows(str(BACKUP))    # slim, PRE-write backup (correct for these 30)

    row_enc = json.JSONEncoder(ensure_ascii=False, default=str)
    listing_blobs: list[bytes] = []
    details: list[dict] = []
    by_state: dict = {}
    by_source: dict = {}
    n = 0
    touched = 0
    changes = []  # for dry-run / audit report

    remaining = set(TARGET_POSITIONS)
    _MISSING = object()
    for pos, (cur, bak) in enumerate(itertools.zip_longest(cur_iter, bak_iter, fillvalue=_MISSING)):
        if cur is _MISSING or bak is _MISSING:
            raise SystemExit(
                "row count mismatch between current board and backup -- refusing to "
                "guess positional alignment. Aborting with NOTHING written."
            )
        n += 1

        if pos in TARGET_POSITIONS:
            remaining.discard(pos)
            touched += 1
            bak_raw = bak.get("raw") if isinstance(bak.get("raw"), dict) else {}
            if not isinstance(cur.get("raw"), dict):
                cur["raw"] = {}
            row_change = {
                "position": pos, "parcel_id": cur.get("parcel_id"),
                "county": cur.get("county"), "street_address": cur.get("street_address"),
                "fields": {},
            }
            for k in KEYS:
                old_present = k in cur["raw"]
                old_val = cur["raw"].get(k) if old_present else None
                new_present = k in bak_raw
                new_val = bak_raw.get(k) if new_present else None
                if old_present != new_present or old_val != new_val:
                    row_change["fields"][k] = {
                        "old": ("<absent>" if not old_present else old_val),
                        "new": ("<absent>" if not new_present else new_val),
                    }
                if new_present:
                    cur["raw"][k] = bak_raw[k]
                else:
                    cur["raw"].pop(k, None)
            changes.append(row_change)

        by_state[str(cur.get("state") or "").strip() or "unknown"] = \
            by_state.get(str(cur.get("state") or "").strip() or "unknown", 0) + 1
        by_source[str(cur.get("source") or "").strip() or "unknown"] = \
            by_source.get(str(cur.get("source") or "").strip() or "unknown", 0) + 1

        raw = cur.get("raw")
        d: dict = {}
        if isinstance(raw, dict):
            for k in LAZY_DETAIL_KEYS:
                if k in raw:
                    d[k] = raw.pop(k)
        details.append(d)
        listing_blobs.append(row_enc.encode(cur).encode("utf-8"))

    print(f"[{time.strftime('%H:%M:%S')}] scanned {n:,} rows in {time.time()-t0:.0f}s")
    print(f"  target positions found/touched: {touched} / {len(TARGET_POSITIONS)}")
    if remaining:
        print(f"  MISSING target positions (never seen!): {sorted(remaining)}", file=sys.stderr)
    print("\n--- changes (old -> new, per touched row) ---")
    for rc in changes:
        print(f"  position {rc['position']} | parcel_id={rc['parcel_id']} county={rc['county']} "
              f"addr={rc['street_address']!r}")
        if not rc["fields"]:
            print("    (no diff -- current already matches backup)")
        for k, v in rc["fields"].items():
            print(f"    {k}: {v['old']!r} -> {v['new']!r}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    if remaining:
        raise SystemExit(
            f"refusing to write: {len(remaining)} target position(s) never seen while "
            f"streaming {n:,} rows: {sorted(remaining)}"
        )

    _manifest_now = load_manifest(DOCS)
    if _manifest_now:
        _expected = ((_manifest_now.get("files") or {}).get("listings.json") or {}).get("records")
        if isinstance(_expected, int) and n != _expected:
            raise SystemExit(
                f"refusing: streamed {n:,} rows but manifest records {_expected:,} -- "
                f"verify with scripts/board_manifest.py --verify before retrying."
            )

    summary = {"notes": (f"revert_multiyear_tax_sibling_rows: reverted two_year_delinquent/"
                         f"multi_year_delinquent_tax on {touched} dedupe_key-collision sibling "
                         f"rows from backfill_multiyear_tax_restatement.py's real run (26 SC "
                         f"Dillon mobile-home rows, 2 Spartanburg, 1 Abbeville, 1 Oconee) to "
                         f"their pre-write backup state -- these siblings are not the same "
                         f"taxable item as the qpaybill-sourced row they shared a dedupe_key "
                         f"with. 6 other rows (Cherokee, Marlboro, Spartanburg 7150829201) were "
                         f"confirmed to be genuinely the same parcel and left untouched.")}
    _count_guard_and_backup(DOCS, listings_path, n, summary)

    _manifest_pre: dict = {
        "listings.json": {**_write_plain_array(listings_path, listing_blobs), "records": n},
    }
    detail_path = DOCS / "listings_detail.json"
    detail_count = len(details)
    detail_bytes = json.dumps(details, ensure_ascii=False, default=str).encode("utf-8")
    del details
    _manifest_pre["listings_detail.json"] = {"bytes": len(detail_bytes),
                                             "sha256": hashlib.sha256(detail_bytes).hexdigest(),
                                             "records": detail_count}
    _atomic_write_bytes(detail_path, detail_bytes)
    _prior_parts = _bp.manifest_parts_block(_bp.read_manifest(DOCS)) or {}
    _parts = _bp.write_parts(DOCS, listing_blobs, hint_rows=_prior_parts.get("rows_per_part"))
    _parts_block = _bp.make_block(_parts["entries"], rows_per_part=_parts["rows_per_part"],
                                  cap=_parts["cap"])
    del listing_blobs
    detail_gz = gzip.compress(detail_bytes, compresslevel=9, mtime=0)
    _manifest_pre["listings_detail.json.gz"] = {"bytes": len(detail_gz),
                                                "sha256": hashlib.sha256(detail_gz).hexdigest(),
                                                "records": detail_count}
    _atomic_write_bytes(DOCS / "listings_detail.json.gz", detail_gz)
    detail_digest = hashlib.sha256(detail_gz).hexdigest()[:16]
    del detail_gz, detail_bytes

    meta_path = DOCS / "run_meta.json"
    prior_meta: dict = {}
    if meta_path.exists():
        try:
            prior_meta = json.loads(meta_path.read_text())
        except Exception:  # noqa: BLE001
            prior_meta = {}
        if not isinstance(prior_meta, dict):
            prior_meta = {}
    prior_board_block = prior_meta.get("board")
    if not isinstance(prior_board_block, dict):
        prior_board_block = None
    slim_count = prior_board_block.get("count") if prior_board_block else None
    shard_meta = prior_board_block.get("detail_shards") if prior_board_block else None

    _now = datetime.utcnow()
    _now_iso = _now.isoformat() + "Z"
    meta = dict(prior_meta)
    meta.update({
        "run_time": _now_iso,
        "total": n,
        "by_state": dict(sorted(by_state.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_source_on_board": dict(sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))),
        "notes": summary["notes"],
        "detail_count": detail_count,
        "detail_digest": detail_digest,
        "board_parts": _parts_block,
    })
    if prior_board_block is not None:
        meta["board"] = prior_board_block
    _apply_health_freshness(meta, prior_meta, summary, _now_iso, _now)
    _atomic_write_bytes(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2).encode("utf-8"))

    try:
        write_manifest(DOCS, _manifest_pre, meta, slim_count=slim_count, shard_meta=shard_meta,
                       parts_block=_parts_block)
    except Exception:  # noqa: BLE001
        try:
            (DOCS / MANIFEST_NAME).unlink(missing_ok=True)
        except OSError:
            pass
        print("manifest write FAILED", file=sys.stderr)

    print(f"\n[{time.strftime('%H:%M:%S')}] wrote reverted board "
          f"({touched} rows reverted) in {time.time()-t0:.0f}s total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
