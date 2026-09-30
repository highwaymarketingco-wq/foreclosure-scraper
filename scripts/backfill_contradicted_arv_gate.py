#!/usr/bin/env python3
"""One-off backfill: re-apply the ARV trust gate to already-published rows whose
raw['calc'] / raw['equity'] carry a derived money figure alongside a CONTRADICTED
arv_flags entry -- the exact invariants scripts/board_selfcheck.py checks under
"no {max_bid_70,wholesale_mao,equity} on a contradicted ARV".

WHY THIS EXISTS
    board_selfcheck.py (rewritten 38b5967d) found the invariant genuinely breached
    on the live 219,143-row board: 97 rows with max_bid_70, 43 with wholesale_mao,
    100 with equity, all published alongside an arv_flags entry that is a member of
    valuation.grading.ARV_FLAGS_CONTRADICTED.

    Root cause (see models.py's Listing.merge() and its new _regate_merged_valuation()
    helper, fixed in this same change): `_deep_merge_dict` unions DICT KEYS -- it can
    overwrite or add a key either side of a merge names, but a key ABSENT from a dict
    is invisible to it, so it can never delete one. calc.to_dict() and
    enrichment_equity's withhold_equity() both drop a gated field's key entirely
    (never write None) -- that is precisely what lets the dashboard/CSV render
    nothing for a withheld figure. So any merge between an OLDER, un-gated copy of a
    lead (from before the contradiction was detected, or before the flag that
    detects it existed) and a freshly re-graded copy of the SAME lead (ARV now
    correctly flagged, derived fields correctly absent) resurrected the stale
    figure: the old copy's key was still there, the new copy had no key to
    overwrite it with, so the union kept the stale one. dedupe() (3 call sites) and
    today's merge_duplicate_rows() both fold duplicate/multi-source copies of one
    property through Listing.merge(), so this could happen on any ordinary run.

    The CODE fix (models.py) stops this from recurring. This script is the
    backfill for the ~100-ish rows already published with the bug's output.

    A fresh full compute()+grade() recompute was deliberately NOT used to fix these
    rows (unlike scripts/recompute_geo_imprecise_confidence.py's approach for a
    different bug): a live check found at least one of these rows recomputes to a
    DIFFERENT arv_expected under today's code (an unrelated, much larger valuation
    change -- a "stale_sale_floor" flag neither on the board nor part of this bug),
    so a full recompute risks bundling an unrelated ARV change into this narrow
    fix. Instead this script re-applies ONLY the existing, already-tested gate
    (valuation.grading.gate_calc_dict -- the "belt and braces" function written
    for exactly this "a board carried over from a run that predates this gate"
    case -- plus enrichment_equity's withhold_equity) to the CURRENTLY PUBLISHED
    calc/equity blocks, unchanged otherwise. arv_expected, arv_flags, notes and
    every other field are left exactly as published; only the fields the gate says
    must not survive a contradicted ARV are removed.

BOARD I/O
    Streamed read-only via board_stream.iter_board_rows() -- no lazy-detail sidecar
    needed (the decision only reads raw['calc'] and raw['equity']). Landed with
    web_artifact.patch_existing_rows(), same as every other targeted backfill this
    session.

COLLISION GUARD (same two-pass pattern as scripts/backfill_tax_owed_amount_owed.py,
see that script's docstring for the incident this class of guard closes). A patch
here is a function of the ONE row's own already-published raw['calc']/raw['equity']
-- if two DISTINCT board rows share a dedupe_key() (a pre-existing un-merged-
duplicate condition), patch_existing_rows() would apply the SAME patch object to
both, which is only correct if their calc/equity blocks already agree. Rather than
assume that, this script runs a tally pass first and drops any key counted more
than once from this run (reported as skipped_collision) -- a missed fix here costs
nothing (the row stays broken, retry once the underlying duplicate is fixed
separately); a wrong guess would push one row's gate decision onto an unrelated one.

USAGE
    .venv/bin/python scripts/backfill_contradicted_arv_gate.py --dry-run
    .venv/bin/python scripts/backfill_contradicted_arv_gate.py
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.valuation.grading import (  # noqa: E402
    ARV_FLAGS_CONTRADICTED, ARV_TRUST_BLOCKS_DERIVED, gate_calc_dict,
)
from foreclosure_scraper.enrichment_equity import (  # noqa: E402
    equity_arv_trust, withhold_equity,
)
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLockBusy, board_lock, patch_existing_rows,
)

DOCS = REPO / "docs"

#: Same identity fields patch_existing_rows()/append_new_rows() use internally.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")


def _engine_running() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", "--",
         r"run_local\.sh|-m foreclosure_scraper|merge_today_sources|resolver_backfill|"
         r"load_board|recompute_valuation|merge_duplicate_rows|board_manifest"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def _dedupe_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def _build_patch(rec: dict) -> tuple[dict | None, dict]:
    """Return (patch or None, debug-info) for one board row.

    None means the row needs no change. A patch mirrors patch_existing_rows()'s
    top-level-shallow raw.update() semantics: {"raw": {"calc": <full replacement
    calc dict>}} and/or {"raw": {"equity": <full replacement equity dict>}} --
    each sub-key REPLACES the row's existing raw['calc']/raw['equity'] wholesale
    (patch_existing_rows does `raw.update(raw_update)`, a shallow top-level merge
    of raw's own keys), so gate_calc_dict/withhold_equity's mutation of a COPY of
    the currently-published dict is exactly what must be sent.
    """
    raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
    calc = raw.get("calc")
    equity = raw.get("equity")

    info = {"had_bad_money": False, "had_bad_equity": False}
    patch_raw: dict = {}

    if isinstance(calc, dict):
        flags = set(calc.get("arv_flags") or [])
        if flags & ARV_FLAGS_CONTRADICTED:
            # Shallow-copy every mutable value too: gate_calc_dict() pop()s keys off
            # (safe on a shallow dict copy) but also calc.setdefault("notes", []).append(...),
            # and setdefault returns the SAME list object a plain dict(calc) would still
            # share with the original -- copy notes/arv_flags explicitly so mutating this
            # working copy can never touch the row's original, unpatched dict too.
            new_calc = dict(calc)
            new_calc["notes"] = list(calc.get("notes") or [])
            new_calc["arv_flags"] = list(calc.get("arv_flags") or [])
            before_keys = set(new_calc.keys())
            gate_calc_dict(new_calc)
            if set(new_calc.keys()) != before_keys or new_calc != calc:
                info["had_bad_money"] = True
                patch_raw["calc"] = new_calc

    # Equity: use the (possibly just-patched) calc for the trust decision, same as
    # models.py's _regate_merged_valuation -- read the FINAL flags, not the raw
    # dict's original ones, so this can't disagree with the calc patch above.
    calc_for_trust = patch_raw.get("calc", calc if isinstance(calc, dict) else {})
    if isinstance(equity, dict) and equity.get("value") is not None:
        arv_flags = sorted((calc_for_trust or {}).get("arv_flags") or [])
        from foreclosure_scraper.valuation.grading import arv_trust
        level = arv_trust(arv_flags, (calc_for_trust or {}).get("arv_expected"),
                          (calc_for_trust or {}).get("arv_withheld"))
        if level in ARV_TRUST_BLOCKS_DERIVED:
            li = Listing.model_construct(raw={"equity": dict(equity)})
            withhold_equity(li, level, arv_flags)
            info["had_bad_equity"] = True
            patch_raw["equity"] = li.raw["equity"]

    if not patch_raw:
        return None, info
    return {"raw": patch_raw}, info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap the number of ROWS SCANNED (testing)")
    args = ap.parse_args()

    if _engine_running():
        print("engine/backfill/another loader is running -- refusing to touch the board",
              file=sys.stderr)
        return 1

    t0 = time.time()
    lock = None
    if not args.dry_run:
        try:
            lock = board_lock(REPO, owner="backfill_contradicted_arv_gate")
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
    key_counts: Counter = Counter()
    pending: dict[str, dict] = {}
    by_source: Counter = Counter()
    money_fixed = 0
    equity_fixed = 0
    examples: list[dict] = []
    no_key = 0

    for rec in iter_board_rows(DOCS / "listings.json.gz"):
        scanned += 1
        key = _dedupe_key(rec)
        if key is None:
            no_key += 1
        else:
            key_counts[key] += 1
            patch, info = _build_patch(rec)
            if patch is not None:
                pending[key] = patch
                by_source[rec.get("source") or "?"] += 1
                if info["had_bad_money"]:
                    money_fixed += 1
                if info["had_bad_equity"]:
                    equity_fixed += 1
                if len(examples) < 8:
                    examples.append({
                        "source": rec.get("source"), "parcel_id": rec.get("parcel_id"),
                        "street_address": rec.get("street_address"),
                        "arv_flags": ((rec.get("raw") or {}).get("calc") or {}).get("arv_flags"),
                        "had_bad_money": info["had_bad_money"],
                        "had_bad_equity": info["had_bad_equity"],
                    })
        if args.limit and scanned >= args.limit:
            break

    collision_keys = {k for k in pending if key_counts[k] > 1}
    for k in collision_keys:
        del pending[k]

    print(f"[{time.strftime('%H:%M:%S')}] scanned {scanned:,} rows in {time.time()-t0:.0f}s")
    print(f"  rows needing a fix: {len(pending) + len(collision_keys):,} "
          f"(money_fixed={money_fixed:,}, equity_fixed={equity_fixed:,})")
    print(f"  dropped as dedupe_key collisions: {len(collision_keys):,}")
    print(f"  no dedupe key at all: {no_key:,}")
    print(f"  patch-ready rows: {len(pending):,}")
    print("  by source:")
    for src, n in by_source.most_common(15):
        print(f"    {n:5,d}  {src}")

    if examples:
        print("\n--- sample (up to 8) ---")
        for ex in examples:
            print(f"  {ex}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    if not pending:
        print("\nnothing to patch")
        return 0

    stats = patch_existing_rows(
        pending,
        {"backfill_contradicted_arv_gate": len(pending),
         "notes": (f"re-gate ARV-contradicted rows (models.py Listing.merge() fix): "
                   f"{len(pending):,} rows patched (money_fixed={money_fixed:,}, "
                   f"equity_fixed={equity_fixed:,}, collisions_skipped={len(collision_keys):,})")},
        docs_dir=DOCS,
    )
    print(f"\n[{time.strftime('%H:%M:%S')}] patched {stats['applied']}/{len(pending)} rows "
          f"(existing board: {stats['existing']:,}, not_found: {stats['not_found']:,}, "
          f"dup_keys: {stats['duplicate_key_matches']:,}) in {time.time()-t0:.0f}s total", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
