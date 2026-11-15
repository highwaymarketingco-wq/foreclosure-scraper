#!/usr/bin/env python3
"""Fix Greene County NC rows whose `parcel_id` is a non-unique NC OneMap `parno`
value, backfilling each affected row's OWN correct `owner_name` (and, on one row,
`defendant`/`description` too) from data that row's OWN scrape already carries, and
promoting `parcel_id` to that same row's own distinct `altparno`.

FOUND (2026-11-15, round-2 identity-collision triage, see
project_vm_push_credentials_missing_and_board_divergence_2026-11-13.md, "Greene"). NC
OneMap's `parno` is NOT a per-parcel-unique id on Greene County's own rows (unlike every
other NC county sampled this project): live-confirmed, one value alone ("3698035243") is
shared by 48 real Greene parcels, and a full-county scan (groupByFieldsForStatistics on
the live ArcGIS layer, `cntyname='GREENE'`) found 90 distinct parno values shared by 2+
parcels each (worst: 104-way), 425 real parcels affected out of Greene's 12,720 total.
`altparno` IS reliably unique on the same live sample (only 4 small, non-numeric-id
exceptions -- "WAYNE" x4, "WI7235" x2, "WA1404" x2, "0525214" x2 -- none overlapping the
affected parcels here). See scripts/scrapers/counties_nc/nc_heir_estate_parcels.py's own
2026-11-15 note for the going-forward scraper fix (Greene-gated altparno preference); this
script is the one-off backfill for board rows this bug already published before that fix
landed.

WHY THIS DOES NOT USE patch_existing_rows()'s normal patches-dict pattern (same reasoning
as scripts/backfill_lincoln_pin_parcel_id.py, read in full before writing this). Every
affected row here shares its CURRENT Listing.dedupe_key() (parcel:NC:greene:<shared-parno>)
with OTHER real, differently-addressed Greene parcels that each need a DIFFERENT correction
-- patch_existing_rows() applies the SAME patch to every row matching a key, by design
(its own docstring), which is exactly backwards here: of the 8 affected board rows found
(3 of them even share ONE key, all under "3698035243"), 6 need a different `owner_name`
each, 1 of those also needs a different `defendant`/`description`, and all 8 need a
DIFFERENT new `parcel_id` (their own distinct altparno). No per-row-unique pre-patch key
is available through that interface for these rows (dedupe_key()'s parcel branch wins
outright whenever parcel_id is present, and there is no way to ask it to fall through).

WHAT THIS DOES INSTEAD: a single streaming pass, built from the EXACT SAME safety
primitives patch_existing_rows() itself uses (board_lock/require_board_lock,
_check_not_changed_since_load, the board-too-large-to-patch guard, _iter_board_records ->
_ArrayFileWriter -> board_parts.write_parts(), the strict existing-row-count guard,
_count_guard_and_backup, the same manifest/run_meta/highwater shape, write_manifest last)
-- imported directly from web_artifact, not reimplemented -- with ONE substitution: instead
of `key = row.dedupe_key(); update = pending.get(key)`, each row's candidate fix is derived
ONLY from that SAME row's own `source`/`state`/`county`/`parcel_id`/`owner_name`/
`defendant`/`raw` fields (never from any other row, never from an external map) -- the
authoritative "what IS correct for this address" was live-verified against the real NC
OneMap FeatureServer for every one of the 8 affected rows BEFORE writing a line of this
script (see GREENE_COLLIDING_PARNOS and the commit message for the live query transcript),
but the VALUE actually written comes from this row's own already-scraped
raw.heir_estate.owner_of_record / parcel_facts.altparno -- fields nc_heir_estate_parcels.py
computed correctly per-row at scrape time and simply never promoted (altparno) or that a
SEPARATE later process (enrichment_gis_attrs.py's parcel_cache.lookup(), keyed the same
ambiguous way) overwrote with a different real parcel's value (owner_name; on one row,
defendant/description too, via a same-key ingest-merge collision). This never adds or
removes a row, exactly like patch_existing_rows().

ALSO FIXES (live-verified, not assumed): the task that found this only flagged
"3698035243" (3 rows). A full-county live scan of every distinct parno value Greene
shares across 2+ real parcels, cross-referenced against every Greene row currently on the
board, found 5 MORE affected rows under 5 OTHER colliding parno values -- 8 rows in all,
all from counties_nc.nc_heir_estate_parcels. See GREENE_COLLIDING_PARNOS below (the full
90-value live snapshot, not just the 6 this board happens to need today) and the dry-run
output for the complete per-row detail.

    python scripts/backfill_greene_parno_altparno.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_greene_parno_altparno.py
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

TARGET_SOURCE = "counties_nc.nc_heir_estate_parcels"

#: Every distinct NC OneMap `parno` value shared by 2+ real Greene County parcels,
#: live-confirmed 2026-11-15 via groupByFieldsForStatistics on
#: services.nconemap.gov/.../NC1Map_Parcels/FeatureServer/1, where cntyname='GREENE'
#: (90 values, 425 affected real parcels; verified the DESC-sorted result's count column
#: drops to 1 immediately after the last entry here, so this is the complete set, not a
#: sample). The blank ("") group (13 rows with no parno at all) is deliberately excluded --
#: those rows have no parcel_id to collide on in the first place (dedupe_key() falls
#: through to the address branch for them), a different, unaffected shape.
GREENE_COLLIDING_PARNOS = frozenset({
    "4610334766", "3698035243", "3688752331", "4606182554", "3670158838",
    "3692439386", "3682106823", "4631251141", "3671750809", "3694429610",
    "3653354206", "3670300746", "3680452982", "3692545641", "3692818129",
    "3672438841", "3670053763", "4519691081", "4632054068", "3676407676",
    "4611446992", "4620141496", "3688943363", "4604372168", "3599972473",
    "3692105448", "3694838160", "3671441197", "4603592718", "4612861485",
    "4620462963", "4642832906", "4508692503", "3653186077", "3653945308",
    "4644161405", "4625090190", "3685875989", "4622880461", "4632276927",
    "4610440273", "4610480019", "3683973955", "4607399117", "4615635101",
    "3672689923", "3690703884", "4601265002", "4615663825", "3652327087",
    "4604666655", "3688325852", "3599186941", "3694571336", "4625446639",
    "4613926463", "3651184820", "3680722761", "4623025465", "4621310398",
    "3598777879", "3672712661", "3599410479", "3655663920", "3681944571",
    "4606843075", "3692703661", "3589862785", "4612062353", "3662792554",
    "4607090199", "3692025036", "3685722642", "3680765746", "3680123474",
    "3685744299", "3662356519", "3653173541", "3690557446", "4613408448",
    "3673093190", "3579497855", "4601041268", "4632156178", "3653857876",
    "3682359491", "3662830383", "3641961404", "3651874257", "3671150762",
})


def _norm(pid) -> str:
    return str(pid or "").strip()


def target_fix(rec: dict) -> dict | None:
    """The field updates THIS row (and only this row's own fields) needs, or None.
    Pure function of `rec` -- never consults any other row, so two rows can never be
    handed the same new parcel_id unless they genuinely already carry the same altparno
    in their own raw data (not something this backfill could introduce)."""
    if str(rec.get("source") or "") != TARGET_SOURCE:
        return None
    if str(rec.get("state") or "").strip().upper() != "NC":
        return None
    if str(rec.get("county") or "").strip().lower() != "greene":
        return None
    pid = _norm(rec.get("parcel_id"))
    if pid not in GREENE_COLLIDING_PARNOS:
        return None
    raw = rec.get("raw")
    if not isinstance(raw, dict):
        return None
    he = raw.get("heir_estate")
    if not isinstance(he, dict):
        return None
    altparno = _norm((he.get("parcel_facts") or {}).get("altparno"))
    correct_owner = _norm(he.get("owner_of_record"))
    if not altparno or not correct_owner:
        return None   # nothing to promote to / nothing to trust as correct -- leave alone

    updates: dict = {"parcel_id": altparno}
    fixed: list[str] = []
    if _norm(rec.get("owner_name")) != correct_owner:
        updates["owner_name"] = correct_owner
        fixed.append("owner_name")
    if _norm(rec.get("defendant")) != correct_owner:
        updates["defendant"] = correct_owner
        updates["description"] = (
            f"Heir/estate owner of record ({correct_owner}) in "
            f"{rec.get('county')} County, {rec.get('state')}")
        fixed.append("defendant+description")
    updates["_old_parcel_id"] = pid          # audit-only, stripped before writing
    updates["_fixed_fields"] = fixed         # audit-only, stripped before writing
    return updates


# ---------------------------------------------------------------------------------------
# DRY RUN: read-only, iter_board_rows only, never touches the board.
# ---------------------------------------------------------------------------------------
def dry_run(docs: Path) -> dict:
    board_path = docs / "listings.json.gz"
    if not board_path.exists():
        board_path = docs / "listings.json"
    total = 0
    greene_total = 0
    samples = []
    by_fixed_field = collections.Counter()
    new_parcel_ids: dict[str, set] = collections.defaultdict(set)
    for rec in iter_board_rows(board_path):
        total += 1
        if str(rec.get("county") or "").strip().lower() == "greene" and \
                str(rec.get("state") or "").strip().upper() == "NC":
            greene_total += 1
        hit = target_fix(rec)
        if not hit:
            continue
        for f in hit["_fixed_fields"]:
            by_fixed_field[f] += 1
        new_parcel_ids[hit["parcel_id"]].add(
            (rec.get("source"), rec.get("street_address")))
        samples.append({
            "street_address": rec.get("street_address"),
            "old_parcel_id": hit["_old_parcel_id"],
            "new_parcel_id": hit["parcel_id"],
            "old_owner_name": rec.get("owner_name"),
            "new_owner_name": updates_owner_name(hit),
            "old_defendant": rec.get("defendant"),
            "new_defendant": hit.get("defendant", rec.get("defendant")),
            "fixed_fields": hit["_fixed_fields"],
        })
    dup_new_ids = {k: v for k, v in new_parcel_ids.items() if len(v) > 1}
    return {
        "board_rows_streamed": total,
        "greene_nc_rows_on_board": greene_total,
        "total_matched": len(samples),
        "by_fixed_field": dict(by_fixed_field),
        "distinct_new_parcel_ids_assigned": len(new_parcel_ids),
        "new_parcel_ids_reused_across_different_rows_SHOULD_BE_EMPTY": dup_new_ids,
        "samples": samples,
    }


def updates_owner_name(hit: dict):
    return hit.get("owner_name")


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
    by_fixed_field: collections.Counter = collections.Counter()
    existing_total = 0
    applied = 0
    applied_rows: list[dict] = []
    seen_new_ids: dict = {}
    reused_ids: list = []

    plain_w = _ArrayFileWriter(listings_path)
    detail_path = docs / "listings_detail.json"
    detail_w = _ArrayFileWriter(detail_path)

    def _rows_for_parts() -> Iterator[bytes]:
        nonlocal existing_total, applied
        for rec in _iter_board_records(docs):
            existing_total += 1
            if isinstance(rec, dict):
                hit = target_fix(rec)
                if hit:
                    old_pid = hit.pop("_old_parcel_id")
                    fixed_fields = hit.pop("_fixed_fields")
                    new_pid = hit["parcel_id"]
                    ident = (rec.get("street_address"), old_pid)
                    prior = seen_new_ids.get(new_pid)
                    if prior is not None and prior != ident:
                        reused_ids.append({"new_parcel_id": new_pid, "a": prior, "b": ident})
                    else:
                        seen_new_ids[new_pid] = ident

                    raw = rec.get("raw")
                    if not isinstance(raw, dict):
                        raw = {}
                        rec["raw"] = raw
                    raw.setdefault("greene_parno_altparno_fix", {
                        "date": "2026-11-15",
                        "old_parcel_id": old_pid,
                        "new_parcel_id": new_pid,
                        "fixed_fields": fixed_fields,
                        "note": ("Greene NC parno not unique (live-confirmed, see "
                                 "project_vm_push_credentials_missing_and_board_"
                                 "divergence_2026-11-13.md); promoted to this row's own "
                                 "altparno and restored this row's own correct owner from "
                                 "raw.heir_estate.owner_of_record."),
                    })
                    for field, value in hit.items():
                        rec[field] = value
                    applied += 1
                    by_fixed_field["parcel_id"] += 1
                    for f in fixed_fields:
                        by_fixed_field[f] += 1
                    if len(applied_rows) < 10:
                        applied_rows.append({
                            "street_address": rec.get("street_address"),
                            "old_parcel_id": old_pid, "new_parcel_id": new_pid,
                            "fixed_fields": fixed_fields,
                        })
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
                f"backfill_greene_parno_altparno: streamed {plain_w.rows} rows into "
                f"listings.json but {existing_total} rows off the board -- should never differ.")
        _plain_ent = plain_w.finish()
        _detail_ent = detail_w.finish()
    except BaseException:
        plain_w.abort()
        detail_w.abort()
        raise

    stats: dict = {
        "existing": existing_total, "matched": applied, "applied": applied,
        "by_fixed_field": dict(by_fixed_field),
        "new_ids_reused_across_different_rows": len(reused_ids),
        "reused_examples": reused_ids[:10],
        "applied_sample": applied_rows,
        "written": False, "total_after": existing_total,
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
                f"backfill_greene_parno_altparno refused: streamed {existing_total:,} rows "
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
        "notes": f"backfill_greene_parno_altparno: {applied} rows patched "
                 f"({dict(by_fixed_field)})",
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
    args = ap.parse_args()

    docs = REPO / "docs"
    if args.dry_run:
        result = dry_run(docs)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    with board_lock(REPO, owner="backfill_greene_parno_altparno", wait=3600, poll=5):
        result = backfill(docs)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
