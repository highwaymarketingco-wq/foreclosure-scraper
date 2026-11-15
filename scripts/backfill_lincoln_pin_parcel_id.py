#!/usr/bin/env python3
"""Promote Lincoln County NC's own already-fetched 10-digit PIN from raw up to the
top-level parcel_id field, for counties_nc.lincoln_vacant and
counties_generic.arcgis_distress.lincoln_county_owned rows that currently publish with
no usable parcel_id.

FOUND (2026-11-15 board-wide no-zip/no-house-number scan, see
project_vm_push_credentials_missing_and_board_divergence_2026-11-13.md, "Lincoln GIS
hidden-PIN"). validation.py nulls any parcel_id under 7 characters as too weak to be
unique (src/foreclosure_scraper/validation.py); Lincoln's own county PARCELID is 5-6
characters, so historically ~15.9k lincoln_vacant rows (and the arcgis_distress layer
that shares its GIS join) published with NO parcel_id at all. Both rows' real 10-digit
NC PIN was fetched the whole time and is still sitting in raw.lincoln_vacant.PIN (see
scrapers/counties_nc/lincoln_vacant.py lines 299-305: "owner decision 2026-10-07" already
switched FRESH scrapes to publish parcel_id=PIN directly, and parcel_alias.py handles the
PARCELID<->PIN fold for rows that still carry a short id token -- but neither retroactively
fixes the EXISTING board backlog whose parcel_id was nulled to nothing before that fix
existed, which is what this one-off backfill does.

LIVE-CONFIRMED on a fresh sample (2026-11-15, this script's own --dry-run, 584,996-row
board, read-only iter_board_rows pass, peak RSS 284MB alongside a concurrent
backfill_incarceration.py run): of Lincoln County rows from these two sources with a
weak/empty parcel_id, EVERY lincoln_vacant row (15,777/15,777) and most
arcgis_distress.lincoln_county_owned rows (31/39) carry a distinct, valid 10-digit PIN in
raw.lincoln_vacant.PIN (that nested raw block is shared by the arcgis_distress GIS join
too, confirmed empirically rather than assumed). The worst colliding address
('addr:w nc 27 hwy|NC:lincoln', 168 rows) resolves to 168 DIFFERENT real PINs -- the
address collision is real, and giving each row its own already-fetched PIN fixes it.

WHY THIS DOES NOT USE patch_existing_rows()'s normal patches-dict pattern (every other
scripts/backfill_*.py does). That function matches purely by recomputing each board row's
OWN current Listing.dedupe_key() and looking it up in a caller-supplied
dict[dedupe_key, update] -- ONE update value per key, documented to apply that SAME
update to every row that matches the key, by design (patch_existing_rows()'s own
docstring: "A dedupe_key() matching MORE than one existing row... gets the SAME patch
applied to every match, not just the first"). That is exactly backwards for this job:
every affected row here is, BY DEFINITION of the bug, sharing its CURRENT dedupe_key()
(the generic addr:<road>|NC:lincoln key, since it has no parcel_id and the road has no
house number) with other real, different properties that each need a DIFFERENT new
parcel_id (their own distinct PIN) -- not the one value a `patches[key]` dict could hold.
There is no key-choice workaround: dedupe_key()'s address branch is tried before
case_number, and patch_existing_rows() unconditionally strips any url:-fallback key before
matching (its own unsafe-identity guard), so no per-row-unique pre-patch key is available
through that interface for these rows at all, confirmed by reading both
Listing.dedupe_key() and patch_existing_rows()'s full body (web_artifact.py) before writing
a line of this script, per the task's own instruction. Splitting the ~15.8k target rows into
many sequential patch_existing_rows() calls (one row per colliding key per call) was also
considered and rejected: the worst key alone would need ~168 full 584,996-row streaming
rewrites, hours of redundant I/O on a board already flagged as disk-sensitive, for no
correctness benefit over doing it once.

WHAT THIS DOES INSTEAD: a single streaming pass, built from the EXACT SAME safety
primitives patch_existing_rows() itself uses (board_lock/require_board_lock,
_check_not_changed_since_load, the board-too-large-to-patch guard,
_iter_board_records -> _ArrayFileWriter -> board_parts.write_parts(), the strict
existing-row-count guard, _count_guard_and_backup, the same manifest/run_meta/highwater
shape, write_manifest last) -- imported directly from web_artifact, not reimplemented --
with ONE substitution: instead of `key = row.dedupe_key(); update = pending.get(key)`, each
row's candidate new value is derived ONLY from that SAME row's own `source`/`parcel_id`/
`raw` fields (never from any other row, never from an external map), so two rows sharing a
collision-prone key can never be assigned the same new value by this script -- each keeps
whatever distinct PIN its own raw block already carries, or is left untouched if it has
none. This never adds or removes a row, exactly like patch_existing_rows().

    python scripts/backfill_lincoln_pin_parcel_id.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_lincoln_pin_parcel_id.py
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterator

REPO = Path("/Users/cashhigh/foreclosure-scraper")
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
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

TARGET_SOURCES = frozenset({
    "counties_nc.lincoln_vacant",
    "counties_generic.arcgis_distress.lincoln_county_owned",
})
_PIN_KEYS = ("PIN", "pin", "Pin")


def _digits10(v) -> str | None:
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s if len(s) == 10 else None


def _norm_parcel(pid) -> str:
    return "".join(ch for ch in str(pid or "").lower() if ch.isalnum())


def _weak_parcel_id(pid) -> bool:
    """Empty, or shorter than validation.py's own 7-char uniqueness floor (the exact nulling
    rule that created this backlog -- see validation.py's county_native_short_parcel gate)."""
    return len(_norm_parcel(pid)) < 7


def find_pin(raw: dict) -> tuple[str | None, str | None]:
    """A row's own distinct 10-digit PIN and where it was found, or (None, None). Scans every
    nested raw sub-block (not just raw['lincoln_vacant']) because arcgis_distress_layers'
    lincoln_county_owned rows were confirmed, on a live sample, to carry it under that SAME
    'lincoln_vacant' raw block name as the vacant-parcels scraper -- block-name-agnostic on
    purpose rather than assuming one source's naming for both."""
    if not isinstance(raw, dict):
        return None, None
    for blk_key, blk_val in raw.items():
        if isinstance(blk_val, dict):
            for fk in _PIN_KEYS:
                pin = _digits10(blk_val.get(fk))
                if pin:
                    return pin, f"raw.{blk_key}.{fk}"
    for fk in _PIN_KEYS:
        pin = _digits10(raw.get(fk))
        if pin:
            return pin, f"raw.{fk}"
    return None, None


def target_new_parcel_id(rec: dict) -> tuple[str, str] | None:
    """(new_pin, found_path) if THIS row (and only this row's own fields) qualifies for the
    backfill, else None. Pure function of `rec` -- never consults any other row, so it can
    never hand two different rows the same value unless they genuinely already carry the
    same PIN in their own raw data (not something this backfill could introduce)."""
    if str(rec.get("source") or "") not in TARGET_SOURCES:
        return None
    if str(rec.get("state") or "").strip().upper() != "NC":
        return None
    if str(rec.get("county") or "").strip().lower() != "lincoln":
        return None
    if not _weak_parcel_id(rec.get("parcel_id")):
        return None
    pin, path = find_pin(rec.get("raw"))
    if not pin:
        return None
    return pin, path


# ---------------------------------------------------------------------------------------
# DRY RUN: read-only, iter_board_rows only, never touches the board.
# ---------------------------------------------------------------------------------------
def dry_run(docs: Path, sample_n: int = 12) -> dict:
    board_path = docs / "listings.json.gz"
    if not board_path.exists():
        board_path = docs / "listings.json"
    total = 0
    by_source = collections.Counter()
    matched_by_source = collections.Counter()
    pin_reuse = collections.defaultdict(set)  # pin -> set of (source, old_identity) using it
    samples = []
    for rec in iter_board_rows(board_path):
        total += 1
        src = str(rec.get("source") or "")
        if src not in TARGET_SOURCES:
            continue
        by_source[src] += 1
        hit = target_new_parcel_id(rec)
        if not hit:
            continue
        pin, path = hit
        matched_by_source[src] += 1
        pin_reuse[pin].add((src, rec.get("street_address")))
        if len(samples) < sample_n:
            samples.append({
                "source": src, "old_parcel_id": rec.get("parcel_id"),
                "street_address": rec.get("street_address"), "new_parcel_id": pin,
                "found_path": path,
            })
    dup_pins = {p: v for p, v in pin_reuse.items() if len(v) > 1}
    cross_source_same_addr = 0
    cross_source_diff_addr = []
    same_source_diff_addr = []
    for pin, idents in dup_pins.items():
        srcs = {s for s, _a in idents}
        addrs = {str(a or "").strip().lower() for _s, a in idents}
        if len(srcs) > 1 and len(addrs) <= 1:
            cross_source_same_addr += 1
        elif len(srcs) > 1:
            cross_source_diff_addr.append({"pin": pin, "identities": sorted(str(i) for i in idents)})
        if len(srcs) == 1 and len(addrs) > 1:
            same_source_diff_addr.append({"pin": pin, "identities": sorted(str(i) for i in idents)})
    return {
        "board_rows_streamed": total, "by_source": dict(by_source),
        "matched_by_source": dict(matched_by_source),
        "total_matched": sum(matched_by_source.values()),
        "distinct_pins_assigned": len(pin_reuse),
        "pins_reused_across_different_old_identities": len(dup_pins),
        "dup_pins_cross_source_same_addr_BENIGN": cross_source_same_addr,
        "dup_pins_cross_source_diff_addr_REVIEW": cross_source_diff_addr,
        "dup_pins_SAME_SOURCE_diff_addr_ALL": same_source_diff_addr,
        "dup_pin_examples": dict(list(dup_pins.items())[:5]),
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
    by_source_patched: collections.Counter = collections.Counter()
    existing_total = 0
    applied = 0
    # Audit-only: a PIN this run assigns to more than one OLD identity (pre-existing
    # separate board rows for what the county's own PIN says is ONE real parcel --
    # verified on the full dry-run, 2026-11-15: every one of the 194 such groups found is
    # address-string drift for the same parcel -- a missing house number, hyphenation, an
    # alternate/corner road name, or a re-addressing between two historical scrapes -- never
    # two distinct real parcels. The PIN (the county's own authoritative id, why it is being
    # promoted to parcel_id at all) is trusted over the free-text address here; this is
    # NEVER used to withhold a patch, only to leave a trail. Each row's new value still
    # comes ONLY from that row's own raw data, so this script itself can never be the
    # reason two genuinely different rows end up sharing a value.
    seen_pins: dict = {}
    pin_reused: list = []

    plain_w = _ArrayFileWriter(listings_path)
    detail_path = docs / "listings_detail.json"
    detail_w = _ArrayFileWriter(detail_path)

    def _rows_for_parts() -> Iterator[bytes]:
        nonlocal existing_total, applied
        for rec in _iter_board_records(docs):
            existing_total += 1
            if isinstance(rec, dict):
                hit = target_new_parcel_id(rec)
                if hit:
                    pin, path = hit
                    ident = (rec.get("street_address"), rec.get("source_url"))
                    prior = seen_pins.get(pin)
                    if prior is not None and prior != ident:
                        pin_reused.append({"pin": pin, "a": prior, "b": ident})
                    else:
                        seen_pins[pin] = ident
                    raw = rec.get("raw")
                    if not isinstance(raw, dict):
                        raw = {}
                        rec["raw"] = raw
                    raw.setdefault("parcel_id_backfill", {
                        "from": path, "pin": pin,
                        "note": "2026-11-15 lincoln hidden-PIN backfill",
                    })
                    rec["parcel_id"] = pin
                    applied += 1
                    by_source_patched[str(rec.get("source") or "")] += 1
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
                f"backfill_lincoln_pin_parcel_id: streamed {plain_w.rows} rows into "
                f"listings.json but {existing_total} rows off the board -- should never differ.")
        _plain_ent = plain_w.finish()
        _detail_ent = detail_w.finish()
    except BaseException:
        plain_w.abort()
        detail_w.abort()
        raise

    stats: dict = {
        "existing": existing_total, "matched": applied,
        "applied": applied, "by_source_patched": dict(by_source_patched),
        "pins_reused_across_old_identities": len(pin_reused),
        "pin_reused_examples": pin_reused[:10],
        "written": False,
        "total_after": existing_total,
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
                f"backfill_lincoln_pin_parcel_id refused: streamed {existing_total:,} rows off "
                f"{listings_path}, but {docs / MANIFEST_NAME} records {_expected:,} for it."
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
        "notes": f"backfill_lincoln_pin_parcel_id: {applied} rows patched "
                 f"({dict(by_source_patched)})",
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
    ap.add_argument("--sample", type=int, default=12)
    args = ap.parse_args()

    docs = REPO / "docs"
    if args.dry_run:
        result = dry_run(docs, sample_n=args.sample)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    with board_lock(REPO, owner="backfill_lincoln_pin_parcel_id", wait=3600, poll=5):
        result = backfill(docs)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
