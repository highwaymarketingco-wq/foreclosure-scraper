#!/usr/bin/env python3
"""Repair a real bug the previous run (scripts/recompute_geo_imprecise_confidence.py)
introduced by relying on web_artifact.patch_existing_rows()'s KEY-based matching.

THE BUG. patch_existing_rows() matches board rows by Listing.dedupe_key() and,
by design, applies the SAME patch to every row that shares a key ("the same
identity is, by this codebase's own definition, the same property" -- correct
for a fact like lat/lng that does not vary by source). But valuation is NOT
identity-invariant: it depends on the row's OWN property_kind/opening_bid/comps,
which genuinely differ between two source records that happen to collide on
dedupe_key(). Measured after the run: of the 10,511 rows recomputed for the
census_geocode ARV-confidence fix, 93 shared a dedupe_key() with a SIBLING row
whose property_kind (or opening_bid) actively DISAGREES -- most commonly one
source calling a parcel "single_family" and another calling the SAME parcel_id
"land". patch_existing_rows() applied the single_family-derived calc/grade to
BOTH rows, so the land-classified sibling is now showing a valuation that was
never computed from its own data.

THE FIX must not go through patch_existing_rows() again -- it has no way to give
two rows sharing a key two different values. This script instead streams the
board (web_artifact._iter_board_records(), sidecar merged) alongside the
PRE-corruption backup (backups/listings_20260930_083549.json) IN LOCKSTEP BY
POSITION (row count and order are provably unchanged: patch_existing_rows only
mutates fields in place). For every row whose dedupe_key() is one of the 93
affected keys (docs list at the top of _run(), loaded from a diagnostics
file), it recomputes THAT ROW's OWN calc/grade/data_quality from its OWN full
data (Listing.model_validate on the sidecar-merged record -- real comps, not
the sibling's). Same safety gate as the original script: if the fresh
arv_expected/rehab_expected does not match this SAME row's PRE-corruption
backup value, something besides the flag changed for this specific row and the
fresh number is not trusted -- the row is reverted to its own backup value
instead of publishing an unvetted number. Untouched rows (everything outside
the 93 keys) pass through byte-for-byte unchanged.

Mirrors patch_existing_rows()'s own write tail exactly (same low-level
writers), because that half of the function was never the problem -- only its
row-matching loop was.

USAGE
    .venv/bin/python scripts/repair_dedupe_key_collision.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python scripts/repair_dedupe_key_collision.py
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
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade  # noqa: E402
from foreclosure_scraper.enrichment_data_quality import enrich_data_quality  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLockBusy, LAZY_DETAIL_KEYS, MANIFEST_NAME, _apply_health_freshness,
    _atomic_write_bytes, _check_not_changed_since_load, _count_guard_and_backup,
    _iter_board_records, _write_plain_array, board_lock, load_manifest,
    require_board_lock, write_manifest,
)

DOCS = REPO / "docs"
BACKUP = REPO / "backups" / "listings_20260930_083549.json"
OVERLAP_FILE = Path(
    "/private/tmp/claude-502/-Users-cashhigh-Desktop/aa9a7e18-6fc9-42eb-81cc-4f5e16885180"
    "/scratchpad/overlap_full.json"
)

_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
          "case_number", "source_url", "listing_type")


def _key_of(rec: dict) -> str | None:
    li = Listing.model_construct(**{k: rec.get(k) for k in _FIELDS})
    try:
        return li.dedupe_key()
    except Exception:  # noqa: BLE001
        return None


def _engine_running() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", "--",
         r"run_local\.sh|-m foreclosure_scraper|merge_today_sources|resolver_backfill|load_board|recompute_valuation|recompute_geo_imprecise"],
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

    with open(OVERLAP_FILE) as f:
        overlap = json.load(f)
    problem_keys = set(overlap.keys())
    print(f"problem dedupe_keys (property_kind/bid disagreement, sibling corrupted): "
          f"{len(problem_keys)}")

    t0 = time.time()
    lock = None
    if not args.dry_run:
        try:
            lock = board_lock(REPO, owner="repair_dedupe_key_collision")
            lock.__enter__()
        except BoardLockBusy as exc:
            print(f"{exc} -- refusing to write.", file=sys.stderr)
            return 1

    try:
        return _run(args, problem_keys, t0)
    finally:
        if lock is not None:
            lock.__exit__(None, None, None)


def _run(args, problem_keys: set, t0) -> int:
    listings_path = DOCS / "listings.json"
    if not args.dry_run:
        require_board_lock(DOCS)
        _check_not_changed_since_load(listings_path)

    cur_iter = _iter_board_records(DOCS)                 # sidecar merged, current (corrupted-in-93) board
    bak_iter = _bp.iter_plain_rows(str(BACKUP))          # slim, PRE-corruption backup

    row_enc = json.JSONEncoder(ensure_ascii=False, default=str)
    listing_blobs: list[bytes] = []
    details: list[dict] = []
    by_state: dict = {}
    by_source: dict = {}
    n = 0
    touched = 0
    fresh_used = 0
    reverted_own = 0
    exceptions = 0
    examples: list[dict] = []

    _MISSING = object()
    for cur, bak in itertools.zip_longest(cur_iter, bak_iter, fillvalue=_MISSING):
        if cur is _MISSING or bak is _MISSING:
            raise SystemExit(
                "row count mismatch between current board and backup -- refusing to "
                "guess positional alignment. Aborting with NOTHING written."
            )
        n += 1
        key = _key_of(cur)
        if key in problem_keys:
            touched += 1
            bak_raw = bak.get("raw") if isinstance(bak.get("raw"), dict) else {}
            bak_calc = bak_raw.get("calc") if isinstance(bak_raw.get("calc"), dict) else {}
            try:
                li = Listing.model_validate(cur)
                c = vcalc.compute(li)
                g = vgrade.grade(li, c)
                new_calc = vcalc.to_dict(c)
                new_grade = vgrade.to_dict(g)
            except Exception as exc:  # noqa: BLE001
                exceptions += 1
                new_calc = None
                new_grade = None

            use_fresh = (
                new_calc is not None
                and new_calc.get("arv_expected") == bak_calc.get("arv_expected")
                and new_calc.get("rehab_expected") == bak_calc.get("rehab_expected")
            )

            if not isinstance(cur.get("raw"), dict):
                cur["raw"] = {}
            if use_fresh:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["calc"] = new_calc
                li.raw["grade"] = new_grade
                try:
                    enrich_data_quality([li])
                except Exception:  # noqa: BLE001
                    pass
                cur["raw"]["calc"] = new_calc
                cur["raw"]["grade"] = new_grade
                if isinstance(li.raw.get("data_quality"), dict):
                    cur["raw"]["data_quality"] = li.raw["data_quality"]
                fresh_used += 1
            else:
                # Fall back to THIS row's own pre-corruption value -- never the
                # sibling's, never a half-trusted fresh number.
                for k in ("calc", "grade", "data_quality"):
                    if k in bak_raw:
                        cur["raw"][k] = bak_raw[k]
                    else:
                        cur["raw"].pop(k, None)
                reverted_own += 1

            if len(examples) < 12:
                examples.append({
                    "key": key, "source": cur.get("source"),
                    "property_kind": cur.get("property_kind"),
                    "used": "fresh" if use_fresh else "own_backup_revert",
                    "arv_expected": (cur["raw"].get("calc") or {}).get("arv_expected"),
                    "arv_confidence": (cur["raw"].get("calc") or {}).get("arv_confidence"),
                })

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
    print(f"  rows touched (matched a problem key): {touched}")
    print(f"    used fresh per-row recompute: {fresh_used}")
    print(f"    reverted to own pre-corruption backup value: {reverted_own}")
    print(f"  exceptions: {exceptions}")
    print("\n--- examples ---")
    for ex in examples:
        print(f"  {ex}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    if touched == 0:
        print("\nnothing to repair")
        return 0

    _manifest_now = load_manifest(DOCS)
    if _manifest_now:
        _expected = ((_manifest_now.get("files") or {}).get("listings.json") or {}).get("records")
        if isinstance(_expected, int) and n != _expected:
            raise SystemExit(
                f"refusing: streamed {n:,} rows but manifest records {_expected:,} -- "
                f"verify with scripts/board_manifest.py --verify before retrying."
            )

    summary = {"notes": (f"repair_dedupe_key_collision: {touched} rows (93 dedupe_key "
                         f"collisions) fixed with own-row recompute ({fresh_used}) or "
                         f"own-row backup revert ({reverted_own}), undoing the "
                         f"recompute_geo_imprecise_confidence.py patch_existing_rows() "
                         f"cross-contamination")}
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

    print(f"\n[{time.strftime('%H:%M:%S')}] wrote repaired board "
          f"({touched} rows fixed) in {time.time()-t0:.0f}s total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
