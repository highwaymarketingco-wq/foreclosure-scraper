#!/usr/bin/env python3
"""Revert the 4 keys (county_deed_ref, county_legal, gis_fill, unbound_property_blocks) on
exactly 6 known sibling-row POSITIONS in docs/listings.json back to their state in the
pre-write backup backups/listings_20261019_005453.json.

WHY. The real backfill run's patch_existing_rows() keyed by Listing.dedupe_key() and, for 6
dedupe-key collisions, applied the SAME patch to BOTH rows sharing that key. In each pair the
sibling row (one of the 6 positions below) is NOT the repair candidate -- it had none of these
4 keys before the patch (backup: {}) -- but now carries data that belongs to the OTHER row's
parcel/owner. This script undoes exactly that, on exactly these 6 positions, nothing else.

MECHANICS mirror scripts/repair_dedupe_key_collision.py's write tail (board_lock, streamed
read of listings.json by board_parts.iter_plain_rows, lazy-detail-key pop into
listings_detail.json, _count_guard_and_backup, _write_plain_array, board_parts.write_parts,
write_manifest) -- but the revert logic itself is new/simple: for each of the 6 positions,
copy the backup row's exact value (or absence) of each of the 4 keys onto the current row;
every other row and every other field passes through byte-for-byte unchanged.

USAGE
    .venv/bin/python scripts/repair_deed_ref_bound_sibling_positions.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python scripts/repair_deed_ref_bound_sibling_positions.py
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
BACKUP = REPO / "backups" / "listings_20261019_005453.json"

TARGET_POSITIONS = {260970, 260949, 168256, 260813, 260885, 260902}
KEYS = ("county_deed_ref", "county_legal", "gis_fill", "unbound_property_blocks")


def _engine_running() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", "--",
         r"run_local\.sh|-m foreclosure_scraper|merge_today_sources|resolver_backfill|load_board|recompute_valuation|recompute_geo_imprecise|repair_dedupe_key_collision"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def _snapshot(rec: dict) -> dict:
    """{key: value-or-MISSING} for the 4 keys of interest, from rec['raw'] (where the
    original backfill wrote them -- these are not LAZY_DETAIL_KEYS, so they live in
    listings.json's own 'raw', never in the listings_detail.json sidecar)."""
    raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
    out = {}
    for k in KEYS:
        out[k] = raw[k] if k in raw else None
    return out, {k: (k in raw) for k in KEYS}


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
            lock = board_lock(REPO, owner="revert_sibling_rows")
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
    bak_iter = _bp.iter_plain_rows(str(BACKUP))    # slim, PRE-write backup (correct for these 6)

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
                "owner": cur.get("owner_name") or cur.get("owner"),
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
        print(f"  position {rc['position']} | parcel_id={rc['parcel_id']} owner={rc['owner']}")
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

    summary = {"notes": (f"revert_sibling_rows: reverted county_deed_ref/county_legal/"
                         f"gis_fill/unbound_property_blocks on {touched} dedupe_key-collision "
                         f"sibling rows (positions {sorted(TARGET_POSITIONS)}) to their "
                         f"pre-write backup state -- undoing patch_existing_rows() landing the "
                         f"deed-ref-bound backfill's patch on both rows sharing a key")}
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
