#!/usr/bin/env python3
"""Corrective, one-off follow-up to scripts/backfill_tax_owed_amount_owed.py.

WHAT WENT WRONG
    That backfill built its patches keyed by Listing.dedupe_key() and landed them via
    web_artifact.patch_existing_rows(), whose own documented contract is: "a dedupe_key()
    matching MORE than one existing row ... gets the SAME patch applied to every match, not
    just the first." 331 rows on the board share a dedupe_key() with a DIFFERENT row (their
    raw parcel_id strings differ but collapse to the same digits after
    Listing._normalize_parcel's zero-pad-stripping, e.g. "0618-74-4754-00000" and
    "061874475400000" both -> "0618744754") -- a pre-existing un-merged-duplicate condition
    this script did not create and does not try to fix. Concretely: one row (an
    arcgis_distress/multi_year_delinquent_tax/etc. tax-ish record) ALSO carries a real,
    unrelated judgment_amount (from enrichment_judgment_amount's text-mining pass, a separate
    and out-of-scope question), so its OWN amount_owed was correctly "judgment"-sourced before
    the backfill and should never have been touched -- but because it shares a key with a
    sibling row that WAS correctly eligible for tax_owed promotion, patch_existing_rows applied
    the sibling's promoted value to BOTH rows, overwriting this one's legitimate judgment figure.

    Verified live 2026-09-29: exactly 331 rows now show `judgment_amount > 0` on the Listing
    itself while `raw['amount_owed']['source'] == 'tax_owed'` -- a value that can only have
    arrived via this collision (promote_tax_owed_amount_owed()/_tax_owed_promotion() never
    generates a "tax_owed" result for a row whose OWN pre-existing amount_owed.source is
    "judgment"; see enrichment_amount_owed._NEVER_OVERWRITE_SOURCES). Sources involved (all
    pre-existing cross-scraper parcel-normalization collisions, not new bugs):
    counties.multi_year_delinquent_tax (224), counties_nc.buncombe_delinquent_tax (61),
    counties_generic.arcgis_distress.buncombe_unpaid_bills (31), counties_nc.rutherford_tax (5),
    counties_sc.sc_dew_lien_registry (4), counties_sc.spartanburg_vacant (3), and one row each
    from counties_nc.buncombe_elderly / asheville_str_permits / nc_heir_estate_parcels.

WHY patch_existing_rows() CANNOT FIX THIS
    Its match is dedupe_key()-only, recomputed from each row's OWN fields -- there is no way to
    tell it "patch only THIS physical row" when a sibling row produces the identical key. Any
    patch submitted under that shared key lands on every row carrying it, which is exactly how
    the original damage happened and would happen again on a naive revert (a patch that
    restores row A's judgment figure would just as surely get applied to row B, corrupting the
    sibling that IS correctly tax_owed-sourced).

THE FIX
    Match on (source, parcel_id, judgment_amount) -- the row's own RAW parcel_id string (not
    dedupe_key()'s normalized form) plus its own judgment_amount, which is unique enough to hit
    only the intended row (verified: zero within-source collisions on raw parcel_id, and the
    judgment_amount equality is a second, independent check). Restores raw['amount_owed'] to
    exactly what enrichment_amount_owed.enrich_amount_owed()'s judgment branch would have
    produced: {value: judgment_amount, source: "judgment", label: "Judgment / indebtedness",
    confidence: "high", is_actual_debt: True}. Targets are loaded from a JSON file (a list of
    {"source", "parcel_id", "judgment_amount"} dicts) rather than hardcoded, so this script can
    be re-pointed if the same collision class recurs elsewhere.

    Reuses web_artifact's OWN low-level streaming + write primitives (the same ones
    patch_existing_rows() uses internally: _iter_board_records, _count_guard_and_backup,
    _write_plain_array, board_parts.write_parts, write_manifest) rather than reinventing them,
    with only the MATCH predicate replaced. Board I/O follows the same
    board_stream.iter_board_rows()-for-reads-only discipline elsewhere in this codebase; the
    mutating pass here is the one place that must touch the low-level writer, exactly as
    patch_existing_rows() itself does.

    python scripts/fix_amount_owed_collision_targets.py --targets <path.json> --dry-run
    python scripts/fix_amount_owed_collision_targets.py --targets <path.json>
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper import board_parts as _bp  # noqa: E402


def _load_targets(path: Path) -> dict[tuple, float]:
    """{(source, parcel_id, round(judgment_amount, 2)): judgment_amount} -- exact match key,
    not dedupe_key(). judgment_amount is PART of the key, not just the value: 19 of the 331
    collision rows share an identical (source, parcel_id) pair with a SECOND, distinct board
    row that has a different judgment_amount (e.g. two snapshots of the same account a cent or
    two apart after interest accrual) -- (source, parcel_id) alone would collapse those two
    targets into one and misapply whichever survived to both rows, reproducing the exact class
    of bug this script exists to fix. Including judgment_amount addresses each row uniquely."""
    raw = json.loads(path.read_text())
    out: dict[tuple, float] = {}
    for t in raw:
        out[(t["source"], t["parcel_id"], round(float(t["judgment_amount"]), 2))] = t["judgment_amount"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    targets = _load_targets(args.targets)
    print(f"loaded {len(targets):,} exact-match correction targets")

    docs = REPO / "docs"
    listings_path = docs / "listings.json"

    lock = contextlib.nullcontext() if args.dry_run else wa.board_lock(
        REPO, owner="fix_amount_owed_collision_targets")

    with lock:
        if not args.dry_run:
            wa.require_board_lock(docs)
            wa._check_not_changed_since_load(listings_path)
            wa._raise_if_board_too_large_to_patch(docs)

        row_enc = json.JSONEncoder(ensure_ascii=False, default=str)
        listing_blobs: list[bytes] = []
        details: list[dict] = []
        by_state: collections.Counter = collections.Counter()
        by_source: collections.Counter = collections.Counter()
        existing_total = 0
        applied = 0
        matched_targets: set = set()

        for rec in wa._iter_board_records(docs):
            existing_total += 1
            rec_ja = rec.get("judgment_amount")
            key = (rec.get("source"), rec.get("parcel_id"),
                  round(float(rec_ja), 2) if isinstance(rec_ja, (int, float)) else None)
            if key in targets and key[2] is not None:
                ja = targets[key]
                # Defensive re-check: only touch a row whose CURRENT amount_owed is still the
                # collision artifact (source == "tax_owed") and whose own judgment_amount still
                # matches what we recorded when the targets file was built. If anything already
                # changed this row since then, leave it alone rather than guess.
                raw = rec.get("raw")
                cur_ao = raw.get("amount_owed") if isinstance(raw, dict) else None
                cur_ja = rec.get("judgment_amount")
                still_matches = (
                    isinstance(raw, dict)
                    and isinstance(cur_ao, dict) and cur_ao.get("source") == "tax_owed"
                    and isinstance(cur_ja, (int, float)) and abs(float(cur_ja) - float(ja)) < 0.005
                )
                if still_matches:
                    raw["amount_owed"] = {
                        "value": round(float(ja), 2),
                        "source": "judgment",
                        "label": "Judgment / indebtedness",
                        "confidence": "high",
                        "is_actual_debt": True,
                    }
                    applied += 1
                    matched_targets.add(key)

            by_state[str(rec.get("state") or "").strip() or "unknown"] += 1
            by_source[str(rec.get("source") or "").strip() or "unknown"] += 1
            d: dict = {}
            r = rec.get("raw")
            if isinstance(r, dict):
                for k in wa.LAZY_DETAIL_KEYS:
                    if k in r:
                        d[k] = r.pop(k)
            details.append(d)
            listing_blobs.append(row_enc.encode(rec).encode("utf-8"))

        not_found = len(targets) - len(matched_targets)
        print(f"existing rows streamed: {existing_total:,}")
        print(f"targets matched and corrected: {applied:,}")
        print(f"targets not found / already changed: {not_found:,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        if applied == 0:
            print("\nnothing to do.")
            return 0

        summary = {"fix_amount_owed_collision_targets": {"applied": applied, "not_found": not_found}}

        _manifest_now = wa.load_manifest(docs)
        if _manifest_now:
            expected = ((_manifest_now.get("files") or {}).get("listings.json") or {}).get("records")
            if isinstance(expected, int) and existing_total != expected:
                raise wa.BoardPatchCountMismatch(
                    f"refusing: streamed {existing_total:,} rows, manifest records {expected:,}")

        wa._count_guard_and_backup(docs, listings_path, existing_total, summary)

        total = existing_total
        manifest_pre: dict = {
            "listings.json": {**wa._write_plain_array(listings_path, listing_blobs), "records": total},
        }
        detail_path = docs / "listings_detail.json"
        detail_count = len(details)
        detail_bytes = json.dumps(details, ensure_ascii=False, default=str).encode("utf-8")
        del details
        manifest_pre["listings_detail.json"] = {
            "bytes": len(detail_bytes), "sha256": hashlib.sha256(detail_bytes).hexdigest(),
            "records": detail_count,
        }
        wa._atomic_write_bytes(detail_path, detail_bytes)
        prior_parts = _bp.manifest_parts_block(_bp.read_manifest(docs)) or {}
        parts = _bp.write_parts(docs, listing_blobs, hint_rows=prior_parts.get("rows_per_part"))
        parts_block = _bp.make_block(parts["entries"], rows_per_part=parts["rows_per_part"],
                                     cap=parts["cap"])
        del listing_blobs
        import gzip
        detail_gz = gzip.compress(detail_bytes, compresslevel=9, mtime=0)
        manifest_pre["listings_detail.json.gz"] = {
            "bytes": len(detail_gz), "sha256": hashlib.sha256(detail_gz).hexdigest(),
            "records": detail_count,
        }
        wa._atomic_write_bytes(docs / "listings_detail.json.gz", detail_gz)
        detail_digest = hashlib.sha256(detail_gz).hexdigest()[:16]
        del detail_gz, detail_bytes

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

        now = datetime.utcnow()
        now_iso = now.isoformat() + "Z"
        meta = dict(prior_meta)
        meta.update({
            "run_time": now_iso,
            "total": total,
            "by_state": dict(sorted(by_state.items(), key=lambda kv: (-kv[1], kv[0]))),
            "by_source_on_board": dict(sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))),
            "notes": summary.get("notes", prior_meta.get("notes", "")),
            "detail_count": detail_count,
            "detail_digest": detail_digest,
            "board_parts": parts_block,
        })
        if prior_board_block is not None:
            meta["board"] = prior_board_block
        wa._apply_health_freshness(meta, prior_meta, summary, now_iso, now)
        wa._atomic_write_bytes(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2).encode("utf-8"))

        try:
            hw_path = docs / "board_highwater.json"
            prev_hw = 0
            if hw_path.exists():
                prev_hw = json.loads(hw_path.read_text()).get("count", 0)
            if total > prev_hw:
                wa._atomic_write_bytes(hw_path, json.dumps(
                    {"count": total, "updated_at": now_iso}, indent=2).encode("utf-8"))
        except Exception:  # noqa: BLE001
            pass

        try:
            wa.write_manifest(docs, manifest_pre, meta, slim_count=slim_count, shard_meta=shard_meta,
                              parts_block=parts_block)
        except Exception:  # noqa: BLE001
            try:
                (docs / wa.MANIFEST_NAME).unlink(missing_ok=True)
            except OSError:
                pass

        print(f"\nwrote board: {total:,} rows, {applied:,} corrected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
