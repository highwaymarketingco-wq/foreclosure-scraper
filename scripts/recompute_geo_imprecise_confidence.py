#!/usr/bin/env python3
"""Targeted valuation recompute for the census_geocode / geo_imprecise_comps fix
(commit 39a588ce), WITHOUT the full-board load_board() a real recompute normally
needs.

WHY THIS EXISTS (HANDOFF.md item 9)
    39a588ce fixed valuation/calc.py so a lead whose `raw.geo_imprecise ==
    "census_geocode"` (a real, resolved street address) is no longer treated the
    same as a bare county/city centroid for the purpose of the `geo_imprecise_comps`
    ARV flag and its MEDIUM-confidence cap. The fix is live in the code but NOT yet
    reflected on the published board: the board's raw['calc'] blocks were written by
    the OLD code and still carry the stale flag/cap on every affected row.

    The obvious fix, `scripts/recompute_valuation.py`, needs `load_board()` over the
    WHOLE board (219,530+ rows, ~2.65 GB source) to do it, and load_board() self-
    refuses above BOARD_LOAD_MAX_SOURCE_MB (1,200 MB) -- and was separately measured
    (2026-09-29, see web_artifact.py's BOARD_LOAD_MAX_SOURCE_MB comment) at an 11+ GB
    "Physical footprint" against a same-sized board even WITH the streaming fix, well
    past this 8 GB Mac's limit. A full-board recompute is therefore a materially
    bigger problem than this fix needs solved.

    THIS SCRIPT recomputes ONLY the rows the fix actually changes:
      1. Stream the board WITH the lazy-detail sidecar merged
         (web_artifact._iter_board_records -- the same generator load_board() and
         patch_existing_rows() themselves consume; never materializes a full
         list[dict] or list[Listing], only ever holds the current row).
      2. Cheaply pre-filter to raw.geo_imprecise == "census_geocode" (~66K rows) and
         then to rows whose PUBLISHED raw.calc.arv_flags already contains
         "geo_imprecise_comps" (~10.5K) -- everything else is discarded immediately,
         never validated into a Listing.
      3. For each survivor, build a real Listing (Listing.model_validate — the same
         call load_board() makes, so this Listing has real comps/cama/rent_comps
         merged in, not the slim board-stream view) and re-run the ACTUAL
         valuation/calc.compute() + valuation/grading.grade() -- the same two calls
         every one of the 13 producers of raw['calc'] in this repo makes. Nothing
         here reimplements calc's logic.
      4. SAFETY GATE: since nothing else about these rows' inputs has changed since
         the last valuation run, the only difference a correct recompute should ever
         produce is in arv_flags / arv_confidence / the verdict fields the trust gate
         (weak-evidence tier) withholds. `arv_expected` (and rehab_expected) must
         come out byte-identical. If it does not, something about this row's
         reconstruction is untrustworthy (most likely a sidecar-merge edge case) and
         it is EXCLUDED from the patch and logged, never guessed at.
      5. Also refresh raw['data_quality'] for a matched row (enrichment_data_quality
         is a pure per-row function of raw['calc'] -- see its own docstring; it is
         NOT given the whole board, just this one row -- run over the single-row list
         via `enrich_data_quality([li])`) so the caption does not go on describing a
         "weak evidence" ARV that calc no longer flags.
      6. Patch via web_artifact.patch_existing_rows() -- the same targeted-mutation
         primitive resolver_backfill_geocode.py / resolver_backfill_parcel.py /
         run_dew_lien_enrichment.py already use for exactly this board's size, under
         BOARD_PATCH_ALLOW_LARGE=1 (the source is over BOARD_PATCH_MAX_SOURCE_MB=2000
         too).

    WHY THIS IS SAFE AS A NARROW, ROW-SCOPED PATCH (investigated, not assumed):
    valuation/calc.compute() and valuation/grading.grade() are pure functions of one
    Listing's own `raw` dict -- comps are `raw.get("comps") or []`, ALREADY selected
    and stored on the row by an earlier (network) enrichment pass, not looked up
    live from other board rows. Neither function takes a list of other listings or
    reads any module-level board state. The ONE place this repo's valuation touches
    cross-row data is enrichment_board_quality.py's shared-centroid clustering (which
    WRITES raw.geo_imprecise in the first place) and distress_score.score_board's
    board-relative normalization -- neither of which this script touches or needs to
    re-run: geo_imprecise_comps is classified WEAK evidence (valuation/grading.py's
    ARV_FLAGS_WEAK_EVIDENCE), which the trust gate only strips the VERDICT for
    (deal_status/deal_message/haircut_needed) -- it never gates max_bid_70/roi_pct/
    equity/distress (those are only blocked on CONTRADICTED/WITHHELD, see
    ARV_TRUST_BLOCKS_DERIVED), so equity and distress_score for these rows were never
    touched by this flag and do not need re-running here.

USAGE
    .venv/bin/python scripts/recompute_geo_imprecise_confidence.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python scripts/recompute_geo_imprecise_confidence.py
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade  # noqa: E402
from foreclosure_scraper.enrichment_data_quality import enrich_data_quality  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLockBusy, _iter_board_records, board_lock, patch_existing_rows,
)

DOCS = REPO / "docs"

_GEO_TAG = "census_geocode"
_FLAG = "geo_imprecise_comps"


def _engine_running() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", "--",
         r"run_local\.sh|-m foreclosure_scraper|merge_today_sources|resolver_backfill|load_board|recompute_valuation"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap the number of MATCHED (census_geocode + flagged) rows processed, for a small verified batch")
    args = ap.parse_args()

    if _engine_running():
        print("engine/backfill/another loader is running -- refusing to touch the board",
              file=sys.stderr)
        return 1

    t0 = time.time()
    lock = None
    if not args.dry_run:
        try:
            lock = board_lock(REPO, owner="recompute_geo_imprecise_confidence")
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
    scanned = 0
    candidates = 0          # raw.geo_imprecise == census_geocode
    was_flagged = 0         # ...and arv_flags already carried geo_imprecise_comps
    fixed = 0                # ...and the fresh recompute drops the flag
    unsafe_skipped = 0       # dropped the flag but arv_expected/rehab drifted too -- excluded
    still_flagged = 0        # flag survives recompute (another reason kept it, or comps changed)
    fully_clean = 0          # fixed AND no other arv_flag remains
    verdict_restored = 0     # deal_status was None before and is set now
    conf_upgraded = 0        # arv_confidence strictly improved (e.g. MEDIUM -> HIGH)
    exceptions = 0

    pending_patches: dict[str, dict] = {}
    examples: list[dict] = []
    anomalies: list[dict] = []

    for rec in _iter_board_records(DOCS):
        scanned += 1
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if raw.get("geo_imprecise") != _GEO_TAG:
            continue
        candidates += 1

        before_calc = raw.get("calc") if isinstance(raw.get("calc"), dict) else {}
        before_flags = set(before_calc.get("arv_flags") or [])
        if _FLAG not in before_flags:
            continue
        was_flagged += 1

        try:
            li = Listing.model_validate(rec)
        except Exception as exc:  # noqa: BLE001
            exceptions += 1
            anomalies.append({"reason": f"validate: {type(exc).__name__}: {exc}",
                              "source": rec.get("source"), "source_url": rec.get("source_url")})
            continue

        try:
            c = vcalc.compute(li)
            g = vgrade.grade(li, c)
        except Exception as exc:  # noqa: BLE001
            exceptions += 1
            anomalies.append({"reason": f"compute: {type(exc).__name__}: {exc}",
                              "source": li.source, "source_url": li.source_url})
            continue

        new_calc = vcalc.to_dict(c)
        new_flags = set(new_calc.get("arv_flags") or [])

        if _FLAG in new_flags:
            still_flagged += 1
            continue

        fixed += 1

        # SAFETY GATE: nothing else about this row's inputs changed since the last
        # valuation run, so the dollar figures must come out identical. Any drift
        # means this row's reconstruction is not trustworthy -- exclude it rather
        # than publish a number nobody asked for.
        before_arv = before_calc.get("arv_expected")
        before_rehab = before_calc.get("rehab_expected")
        new_arv = new_calc.get("arv_expected")
        new_rehab = new_calc.get("rehab_expected")
        if before_arv != new_arv or before_rehab != new_rehab:
            unsafe_skipped += 1
            anomalies.append({
                "reason": "arv/rehab drifted, not just the flag/confidence",
                "key_source": li.source, "source_url": li.source_url,
                "before_arv": before_arv, "new_arv": new_arv,
                "before_rehab": before_rehab, "new_rehab": new_rehab,
            })
            continue

        if not new_flags:
            fully_clean += 1

        before_grade = raw.get("grade") if isinstance(raw.get("grade"), dict) else {}
        new_grade = vgrade.to_dict(g)
        if before_calc.get("deal_status") is None and new_calc.get("deal_status") is not None:
            verdict_restored += 1
        conf_rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        if conf_rank.get(str(new_calc.get("arv_confidence")), -1) > \
                conf_rank.get(str(before_calc.get("arv_confidence")), -1):
            conf_upgraded += 1

        # Refresh data_quality off the FRESH calc -- pure per-row function, given
        # only this one Listing, so it cannot see (or affect) any other row.
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["calc"] = new_calc
        li.raw["grade"] = new_grade
        try:
            enrich_data_quality([li])
        except Exception:  # noqa: BLE001
            pass  # calc/grade patch still valid even if this caption refresh fails

        patch: dict = {"raw": {"calc": new_calc, "grade": new_grade}}
        if isinstance(li.raw.get("data_quality"), dict):
            patch["raw"]["data_quality"] = li.raw["data_quality"]

        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            exceptions += 1
            continue
        pending_patches[key] = patch

        if len(examples) < 8:
            examples.append({
                "source": li.source, "source_url": li.source_url,
                "parcel_id": li.parcel_id, "street_address": li.street_address,
                "before_conf": before_calc.get("arv_confidence"),
                "after_conf": new_calc.get("arv_confidence"),
                "before_flags": sorted(before_flags),
                "after_flags": sorted(new_flags),
                "before_deal": before_calc.get("deal_status"),
                "after_deal": new_calc.get("deal_status"),
            })

        if args.limit and fixed - unsafe_skipped >= args.limit:
            print(f"[{time.strftime('%H:%M:%S')}] --limit {args.limit} reached at "
                  f"scanned={scanned:,}, stopping scan early", flush=True)
            break

    print(f"[{time.strftime('%H:%M:%S')}] scanned {scanned:,} board rows in "
          f"{time.time()-t0:.0f}s", flush=True)
    print(f"  census_geocode candidates:      {candidates:,}")
    print(f"  ...already carrying {_FLAG}: {was_flagged:,}")
    print(f"  ...flag survives recompute:     {still_flagged:,}")
    print(f"  ...flag dropped (fixed):        {fixed:,}")
    print(f"    unsafe (arv/rehab drifted, excluded): {unsafe_skipped:,}")
    print(f"    fully clean (no other arv_flag left): {fully_clean:,}")
    print(f"    verdict restored (deal_status now set): {verdict_restored:,}")
    print(f"    confidence upgraded (e.g. MEDIUM->HIGH): {conf_upgraded:,}")
    print(f"  exceptions: {exceptions:,}")
    print(f"  patch-ready rows: {len(pending_patches):,}")

    if examples:
        print("\n--- sample before/after (up to 8) ---")
        for ex in examples:
            print(f"  {ex['source']} | {ex['parcel_id'] or ex['street_address']}")
            print(f"    conf {ex['before_conf']} -> {ex['after_conf']}   "
                  f"deal {ex['before_deal']} -> {ex['after_deal']}")
            print(f"    flags {ex['before_flags']} -> {ex['after_flags']}")

    if anomalies:
        print(f"\n--- anomalies (up to 10 of {len(anomalies)}) ---")
        for a in anomalies[:10]:
            print(f"  {a}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    if not pending_patches:
        print("\nnothing to patch")
        return 0

    stats = patch_existing_rows(
        pending_patches,
        {"recompute_geo_imprecise_confidence": len(pending_patches),
         "notes": (f"census_geocode ARV-confidence fix (39a588ce): {len(pending_patches):,} rows "
                   f"lost {_FLAG} on recompute (fully_clean={fully_clean:,}, "
                   f"conf_upgraded={conf_upgraded:,}, verdict_restored={verdict_restored:,})")},
        docs_dir=DOCS,
    )
    print(f"\n[{time.strftime('%H:%M:%S')}] patched {stats['applied']}/{len(pending_patches)} rows "
          f"(existing board: {stats['existing']:,}, not_found: {stats['not_found']:,}, "
          f"dup_keys: {stats['duplicate_key_matches']:,}) in {time.time()-t0:.0f}s total", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
