#!/usr/bin/env python3
"""Restore Newberry County SC's own qpaybill "Map Number" from
raw.qpaybill_roll.identification_no up to the top-level parcel_id field, for the
28-key / 57-row no-zip/no-house-number backlog validation.py's missing
Newberry carve-out created.

FOUND (2026-11-15, 28-key mixed/residual triage of the board-wide no-zip/no-house-number
scan -- see project_vm_push_credentials_missing_and_board_divergence_2026-11-13.md,
"Mixed/residual"). validation.py nulls any parcel_id under 7 characters as too weak to be
unique (its own COUNTY_NATIVE_SHORT_PARCEL carve-out covers 6 NC counties but, until this
same investigation's companion fix, zero SC ones); Newberry's own qpaybill "Map Number"
(e.g. "639-90", "25-1") normalizes to 3-6 characters, always under that floor. With
parcel_id nulled, every Newberry counties_sc.qpaybill_delinquent_roll row with no zip and
a rural road-only situs (no house number) fell to dedupe_key()'s weak
addr:<road>|SC:newberry branch. This is NOT a qpaybill_delinquent_roll.py bug and is
unrelated to fe7c557a (Spartanburg bulk-buyer shared-ident false-merge) or 9ff67c2e
(Sumter _road_core false-split), both inside that module's own _to_listings(): every row
here carries exactly one ident, never merged or split by that function.

LIVE-CONFIRMED on the real 28-key population (2026-11-15, newberrytreasurer.qpaybill.com,
5 owner-name searches): every one of the 28 keys' idents is Newberry's real, currently-in-
use map number. Two keys are worse than a stale duplicate -- a genuine identity collision,
not just an unmerged re-scrape:
    PEARSON JAMES KEITH & CONNIE M  ident 574-2   'HWY 353'  (live-confirmed, 2026 bill)
    CURRY JOE WILLIAM EST &         ident 687-12  'HWY 33'   (live-confirmed, 2026 bill)
  -- one named road, no house number, two different real parcels forced onto one addr:
  key; the physical row for ident 687-12 has its OWN raw.qpaybill_roll block correctly
  recording "HWY 33"/Curry, but its TOP-LEVEL street_address was overwritten to "HWY 353"
  at some earlier point (most likely an earlier fuzzy/weak-identity merge pass), so this
  row currently misreports Curry's real delinquency as if it were on Pearson's road.
    REYNOLDS GAIL K   idents 140-25/140-26/140-28   'ROCKY CREEK RD'  (all 3 live-confirmed)
  -- three different real parcels, same owner, same road, no house number.

WHY THIS DOES NOT USE patch_existing_rows()'s normal patches-dict pattern (every other
scripts/backfill_*.py does), same reasoning as scripts/backfill_lincoln_pin_parcel_id.py
(read in full before writing this one): that function matches purely by recomputing each
board row's OWN current Listing.dedupe_key() and looking it up in a caller-supplied
dict[dedupe_key, update] -- ONE update value per key, applied to EVERY row that matches
that key. Every affected row here is, BY DEFINITION of the bug, sharing its CURRENT
dedupe_key() (the generic addr:<road>|SC:newberry key) with 0-2 other rows that each need
their OWN, possibly DIFFERENT, restored ident -- exactly backwards for a single shared
patch value. A single streaming pass with a pure per-row transform (this script), built
from patch_existing_rows()'s own safe-write primitives (imported, not reimplemented), is
the same fix shape the Lincoln PIN backfill already used for the identical reason.

Two independent fields are restored, each ONLY from that SAME row's own raw data (never
from any other row, so two rows sharing a collision-prone key can never be assigned a
value that did not already, distinctly, belong to each of them):
  parcel_id       <- raw.qpaybill_roll.identification_no (every one of the 57 rows)
  street_address  <- raw.qpaybill_roll.property_address, ONLY when it disagrees with the
                     row's own current top-level street_address (the Curry row above; every
                     other row's own raw block already agrees with its top-level field, so
                     this is a no-op for them).

Scope is deliberately narrow -- counties_sc.qpaybill_delinquent_roll rows in Newberry
County with an empty zip_code and no leading house-number digit in street_address, the
EXACT selection that produced the 28-key / 57-row population this investigation
enumerated and live-verified. A Newberry qpaybill row WITH a zip or a house number is not
part of today's visible duplicate-row/collision symptom and is left untouched; the
validation.py carve-out (this investigation's other half) is what protects those -- and
every future Newberry re-scrape -- going forward.

    python scripts/backfill_newberry_qpaybill_parcel_id.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_newberry_qpaybill_parcel_id.py
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterator

REPO = Path("/Users/cashhigh/foreclosure-scraper")
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.validation import county_native_short_parcel  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    LAZY_DETAIL_KEYS,
    MANIFEST_NAME,
    BoardPatchCountMismatch,
    _ArrayFileWriter,
    _apply_health_freshness,
    _atomic_write_bytes,
    _board_file_present,
    _check_not_changed_since_load,
    _iter_board_records,
    _raise_if_board_too_large_to_patch,
    board_lock,
    load_manifest,
    require_board_lock,
    write_manifest,
)
from foreclosure_scraper import board_parts as _bp  # noqa: E402

TARGET_SOURCE = "counties_sc.qpaybill_delinquent_roll"
_LEADING_DIGIT_RE = re.compile(r"^\s*\d")


def _norm(v) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def _in_scope(rec: dict) -> bool:
    """The exact no-zip/no-house-number Newberry qpaybill selection this investigation
    enumerated -- never broader."""
    if str(rec.get("source") or "") != TARGET_SOURCE:
        return False
    if str(rec.get("state") or "").strip().upper() != "SC":
        return False
    if str(rec.get("county") or "").strip().lower() != "newberry":
        return False
    if str(rec.get("zip_code") or "").strip():
        return False
    street = rec.get("street_address")
    if not street or not str(street).strip():
        return False
    if _LEADING_DIGIT_RE.match(str(street)):
        return False
    return True


def target_update(rec: dict) -> dict | None:
    """Field updates for THIS row, derived only from this row's own raw.qpaybill_roll
    block, or None. Pure function of `rec` -- never consults any other row."""
    if not _in_scope(rec):
        return None
    raw = rec.get("raw")
    qr = raw.get("qpaybill_roll") if isinstance(raw, dict) else None
    if not isinstance(qr, dict):
        return None
    ident = str(qr.get("identification_no") or "").strip()
    if not ident or not county_native_short_parcel("SC", "Newberry", ident):
        return None  # not the native map-number shape this fix covers -- leave alone
    update: dict = {}
    if _norm(rec.get("parcel_id")) != _norm(ident):
        update["parcel_id"] = ident
    own_addr = qr.get("property_address")
    if own_addr and _norm(own_addr) != _norm(rec.get("street_address")):
        # this row's own raw block disagrees with its top-level field -- an earlier merge
        # overwrote it with a sibling row's value (the live-verified Curry/687-12 case);
        # the row's OWN raw block is the authoritative record of what THIS source scraped.
        update["street_address"] = own_addr
    return update or None


# ---------------------------------------------------------------------------------------
# DRY RUN: read-only, iter_board_rows only, never touches the board.
# ---------------------------------------------------------------------------------------
def dry_run(docs: Path, sample_n: int = 30) -> dict:
    board_path = docs / "listings.json.gz"
    if not board_path.exists():
        board_path = docs / "listings.json"
    total = 0
    in_scope_rows = 0
    matched = 0
    parcel_id_fixes = 0
    street_address_fixes = 0
    samples = []
    for rec in iter_board_rows(board_path):
        total += 1
        if not _in_scope(rec):
            continue
        in_scope_rows += 1
        update = target_update(rec)
        if not update:
            continue
        matched += 1
        if "parcel_id" in update:
            parcel_id_fixes += 1
        if "street_address" in update:
            street_address_fixes += 1
        if len(samples) < sample_n:
            samples.append({
                "owner_name": rec.get("owner_name"), "old_parcel_id": rec.get("parcel_id"),
                "old_street_address": rec.get("street_address"), "update": update,
                "first_seen": rec.get("first_seen"),
            })
    return {
        "board_rows_streamed": total, "in_scope_rows": in_scope_rows, "matched": matched,
        "parcel_id_fixes": parcel_id_fixes, "street_address_fixes": street_address_fixes,
        "samples": samples,
    }


# ---------------------------------------------------------------------------------------
# REAL WRITE: one streaming pass, mirrors patch_existing_rows()'s own safe-write skeleton
# (same lock/guard/write primitives, imported not reimplemented) with a self-contained
# per-row transform in place of patch_existing_rows()'s identity-keyed `patches` dict.
# ---------------------------------------------------------------------------------------
def backfill(docs_dir: Path | str = "docs") -> dict:
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)
    listings_path = docs / "listings.json"

    require_board_lock(docs)
    _check_not_changed_since_load(listings_path)
    _raise_if_board_too_large_to_patch(docs)

    if not _board_file_present(listings_path):
        return {"existing": 0, "matched": 0, "applied": 0, "written": False, "total_after": 0}

    row_enc = json.JSONEncoder(ensure_ascii=False, default=str)
    by_state: collections.Counter = collections.Counter()
    by_source: collections.Counter = collections.Counter()
    existing_total = 0
    applied = 0
    parcel_id_fixes = 0
    street_address_fixes = 0
    examples: list = []

    plain_w = _ArrayFileWriter(listings_path)
    detail_path = docs / "listings_detail.json"
    detail_w = _ArrayFileWriter(detail_path)

    def _rows_for_parts() -> Iterator[bytes]:
        nonlocal existing_total, applied, parcel_id_fixes, street_address_fixes
        for rec in _iter_board_records(docs):
            existing_total += 1
            if isinstance(rec, dict):
                update = target_update(rec)
                if update:
                    before = {"parcel_id": rec.get("parcel_id"),
                              "street_address": rec.get("street_address")}
                    if "parcel_id" in update:
                        rec["parcel_id"] = update["parcel_id"]
                        parcel_id_fixes += 1
                    if "street_address" in update:
                        rec["street_address"] = update["street_address"]
                        street_address_fixes += 1
                    raw = rec.get("raw")
                    if not isinstance(raw, dict):
                        raw = {}
                        rec["raw"] = raw
                    raw.setdefault("parcel_id_backfill", {
                        "before": before, "after": update,
                        "note": "2026-11-15 newberry qpaybill 28-key backfill",
                    })
                    applied += 1
                    if len(examples) < 10:
                        examples.append({"owner_name": rec.get("owner_name"),
                                         "before": before, "after": update})
            by_state[str(rec.get("state") or "").strip() or "unknown"] += 1
            by_source[str(rec.get("source") or "").strip() or "unknown"] += 1
            raw = rec.get("raw")
            d: dict = {}
            if isinstance(raw, dict):
                for k in LAZY_DETAIL_KEYS:
                    if k in raw:
                        d[k] = raw.pop(k)
            detail_w.add(row_enc.encode(d).encode("utf-8"))
            blob = row_enc.encode(rec).encode("utf-8")
            plain_w.add(blob)
            yield blob

    try:
        _prior_parts = _bp.manifest_parts_block(_bp.read_manifest(docs)) or {}
        _parts = _bp.write_parts(docs, _rows_for_parts(), hint_rows=_prior_parts.get("rows_per_part"))
        if plain_w.rows != existing_total:
            raise RuntimeError(
                f"backfill_newberry_qpaybill_parcel_id: streamed {plain_w.rows} rows into "
                f"listings.json but {existing_total} rows off the board -- should never differ.")
        _plain_ent = plain_w.finish()
        _detail_ent = detail_w.finish()
    except BaseException:
        plain_w.abort()
        detail_w.abort()
        raise

    stats: dict = {
        "existing": existing_total, "matched": applied, "applied": applied,
        "parcel_id_fixes": parcel_id_fixes, "street_address_fixes": street_address_fixes,
        "examples": examples, "written": False, "total_after": existing_total,
    }
    if applied == 0:
        plain_w.abort()
        detail_w.abort()
        return stats

    _manifest_now = load_manifest(docs)
    if _manifest_now:
        _expected = ((_manifest_now.get("files") or {}).get("listings.json") or {}).get("records")
        if isinstance(_expected, int) and existing_total != _expected:
            plain_w.abort()
            detail_w.abort()
            raise BoardPatchCountMismatch(
                f"backfill_newberry_qpaybill_parcel_id refused: streamed {existing_total:,} rows "
                f"off {listings_path}, but {docs / MANIFEST_NAME} records {_expected:,} for it."
            )

    from foreclosure_scraper.web_artifact import _count_guard_and_backup  # noqa: E402
    _count_guard_and_backup(docs, listings_path, existing_total, {})

    total = existing_total
    _parts_block = _bp.make_block(_parts["entries"], rows_per_part=_parts["rows_per_part"],
                                  cap=_parts["cap"])
    plain_w.commit()
    detail_w.commit()

    _manifest_pre: dict = {"listings.json": {**_plain_ent, "records": total}}
    detail_count = detail_w.rows
    _manifest_pre["listings_detail.json"] = {**_detail_ent, "records": detail_count}
    detail_gz = gzip.compress(detail_path.read_bytes(), compresslevel=9, mtime=0)
    _manifest_pre["listings_detail.json.gz"] = {
        "bytes": len(detail_gz), "sha256": hashlib.sha256(detail_gz).hexdigest(),
        "records": detail_count,
    }
    _atomic_write_bytes(docs / "listings_detail.json.gz", detail_gz)
    detail_digest = hashlib.sha256(detail_gz).hexdigest()[:16]
    del detail_gz

    meta_path = docs / "run_meta.json"
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
        "total": total,
        "by_state": dict(sorted(by_state.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_source_on_board": dict(sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))),
        "notes": f"backfill_newberry_qpaybill_parcel_id: {applied} rows patched "
                 f"(parcel_id={parcel_id_fixes}, street_address={street_address_fixes})",
        "detail_count": detail_count,
        "detail_digest": detail_digest,
        "board_parts": _parts_block,
    })
    if prior_board_block is not None:
        meta["board"] = prior_board_block
    _apply_health_freshness(meta, prior_meta, {}, _now_iso, _now)
    _atomic_write_bytes(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2).encode("utf-8"))

    try:
        _hw_path = docs / "board_highwater.json"
        _prev_hw = 0
        if _hw_path.exists():
            _prev_hw = json.loads(_hw_path.read_text()).get("count", 0)
        if total > _prev_hw:
            _atomic_write_bytes(_hw_path, json.dumps(
                {"count": total, "updated_at": _now_iso}, indent=2).encode("utf-8"))
    except Exception:  # noqa: BLE001
        pass

    try:
        write_manifest(docs, _manifest_pre, meta, slim_count=slim_count, shard_meta=shard_meta,
                       parts_block=_parts_block)
    except Exception:  # noqa: BLE001
        try:
            (docs / MANIFEST_NAME).unlink(missing_ok=True)
        except OSError:
            pass

    stats["written"] = True
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sample", type=int, default=30)
    args = ap.parse_args()

    docs = REPO / "docs"
    if args.dry_run:
        result = dry_run(docs, sample_n=args.sample)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    with board_lock(REPO, owner="backfill_newberry_qpaybill_parcel_id", wait=3600, poll=5):
        result = backfill(docs)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
