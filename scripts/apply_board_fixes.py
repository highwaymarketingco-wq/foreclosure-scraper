#!/usr/bin/env python3
"""Apply every board data fix from the 2026-09-21 audit in ONE load and ONE write.

Why one process: a board load is 2.8 GB and a write adds a 1.3 GB backup, on an 8 GB Mac that
is already swapping. Nine separate scripts would be nine load/write cycles. Each fix exposes
`apply_rows(rows, *, dry_run=False) -> dict` (docs/data_quality_fixes_2026-09-21.md section 0),
so this driver loads once, runs them in dependency order, and writes once. A failing step aborts
BEFORE the write, so a half-applied board is never saved.

    python scripts/apply_board_fixes.py                 # dry run: loads the board, runs every step
                                                        # with dry_run=True, prints counters, writes nothing
    python scripts/apply_board_fixes.py --apply         # ONLY board process (about 3 GB)
    python scripts/apply_board_fixes.py --steps county,flip --apply

Run it as the only board process; recompute_valuation.py and rank_board_standalone.py follow it.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

# (key, module, note). Order matters; the reason for each dependency is in
# docs/data_quality_fixes_2026-09-21.md section 0.
STEPS = [
    ("resolver", "undo_resolver_middle_conflicts", "withdraw proven wrong name-to-property resolutions"),
    ("ptscloud", "promote_ptscloud_block", "Henderson PTS numbers -> real PINs"),
    ("accounts", "map_account_ids_to_parcels", "Laurens account numbers -> TMS; Rutherford PIN -> REID"),
    ("county", "backfill_missing_county", "county for rows with none"),
    ("flip", "quarantine_flip_leaks", "stamp flip-type leads outside the 18 counties"),
    ("address", "fill_address_from_parcel", "street address from the parcel cache"),
    ("join", "join_parcel_cache_to_board", "owner mailing, value, sqft from the parcel cache"),
    ("divorce", None, "stamp raw.divorce.match (middle-initial verdict)"),
    ("phones", None, "SC phone identity gate: do_not_dial on unverified matches"),
]


def _step_divorce(rows, dry_run):
    from annotate_divorce_match import verdict_for
    c: Counter = Counter()
    for li in rows:
        raw = li.raw if isinstance(li.raw, dict) else {}
        v = verdict_for(li.owner_name, raw.get("divorce"))
        if v:
            if not dry_run:
                raw["divorce"]["match"] = v
            c[v] += 1
    return dict(c)


def _step_phones(rows, dry_run):
    from foreclosure_scraper import enrichment_sc_phone as G
    xref = G.flag_unverified_xref_phones(rows, apply=not dry_run)
    lane = G.flag_lane_phones(rows, apply=not dry_run)
    xref = {k: v for k, v in xref.items() if k not in ("by_county", "reasons")}
    return {"xref": xref, "lane": lane}


def run_steps(rows, wanted: set[str] | None, dry_run: bool, log=lambda m: print(m, flush=True)) -> dict:
    out: dict = {}
    for key, modname, note in STEPS:
        if wanted and key not in wanted:
            continue
        t0 = time.time()
        n_before = len(rows)
        log(f"[{key}] {note} ...")
        if modname is None:
            res = {"divorce": _step_divorce, "phones": _step_phones}[key](rows, dry_run)
        else:
            mod = importlib.import_module(modname)
            res = mod.apply_rows(rows, dry_run=dry_run)
            backup = res.pop("_backup", None) if isinstance(res, dict) else None
            if backup and not dry_run and getattr(mod, "BACKUP_NAME", None):
                import _dq_common
                path = _dq_common.write_backup(mod.BACKUP_NAME, backup)
                res["backup_file"] = str(path)
        if len(rows) != n_before:
            raise RuntimeError(f"step {key} changed the row count ({n_before} -> {len(rows)}); refusing to continue")
        out[key] = res
        log(f"[{key}] done in {time.time() - t0:.0f}s: {res}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the board (board_lock + load_board + write_artifact)")
    ap.add_argument("--steps", default="", help="comma list of step keys to run (default all): "
                    + ",".join(k for k, _m, _n in STEPS))
    args = ap.parse_args()
    wanted = {s.strip() for s in args.steps.split(",") if s.strip()} or None
    unknown = (wanted or set()) - {k for k, _m, _n in STEPS}
    if unknown:
        print(f"unknown steps: {sorted(unknown)}", file=sys.stderr)
        return 2

    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    lock = board_lock(REPO, owner="apply_board_fixes") if args.apply else contextlib.nullcontext()
    with lock:
        rows = load_board(REPO / "docs")
        n = len(rows)
        print(f"board rows: {n:,}", flush=True)
        results = run_steps(rows, wanted, dry_run=not args.apply)
        assert len(rows) == n, "row count changed, refusing to write"
        if not args.apply:
            print("\nDRY RUN, nothing written. Re-run with --apply (as the only board process).")
            return 0
        write_artifact(rows, {"apply_board_fixes": {k: (v if isinstance(v, dict) else {}) for k, v in results.items()}},
                       docs_dir=REPO / "docs")
        print(f"\nwrote board: {n:,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
