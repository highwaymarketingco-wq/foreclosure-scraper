#!/usr/bin/env python3
"""Apply BOTH pending fill-only board repairs in ONE load/write cycle.

WHY THIS EXISTS RATHER THAN RUNNING THE TWO SCRIPTS BACK TO BACK
    write_artifact() on the 94,384-row board is the expensive, risky step on this
    machine, not the mutation. Measured 2026-09-10: the scheduled
    daily_api_refresh.py sat inside write_artifact for 2h50m at 1.9 GB RSS with
    68 MB of system memory free and no output file open, holding the board lock
    the whole time, and had to be killed. Running two scripts means paying for
    that twice and holding the lock twice as long, so both fills share one cycle.

    It also removes a lost-update window: two sequential runs each load the board,
    and anything that writes between them is clobbered by the second load's stale
    copy.

WHAT IT APPLIES, both fill-only -- neither adds nor removes a row, so the
web_artifact count guard is untouched and the assert below proves it:

  1. logs/liensnc_related.jsonl  ->  raw.liensnc_related
     The 6-hour related-filings harvest. Its output was going to the sidecar
     because RAW_KEEP silently dropped the key on an earlier run; the key is in
     RAW_KEEP now (tests/test_raw_keep_covers_enrichers.py pins it) and the
     sidecar is the durable copy, so the merge is replayable.

  2. county typo / town-name repair  ->  li.county (+ raw.county_repaired_from)
     `county` drives routing, scope_repass and every per-county tally, so a row
     whose county is not a real county is unroutable and inflates coverage counts
     with fake counties. City-lookup first, then the seat table, then fuzzy at 85,
     and anything left is CLEARED -- see the Stanley/Stanly and Leland/Cleveland
     traps documented in scripts/repair_county_typos_and_towns.py.

Logic is IMPORTED from the two reviewed scripts, not retyped, so their tests
(tests/test_county_typo_repair.py) still govern the behaviour that runs here.

    python scripts/apply_pending_board_fills.py --dry-run
    python scripts/apply_pending_board_fills.py
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    merge = _load("liensnc_merge", REPO / "scripts" / "merge_liensnc_related_sidecar.py")
    repair = _load("county_repair", REPO / "scripts" / "repair_county_typos_and_towns.py")

    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact
    try:
        from foreclosure_scraper._upstate_city_to_county import upstate_county_for
    except ImportError:
        upstate_county_for = lambda _c: None  # noqa: E731

    def city_lookup(c):
        try:
            got = upstate_county_for((c or "").strip())
        except Exception:  # noqa: BLE001
            return None
        if not got:
            return None
        return got[0] if isinstance(got, (tuple, list)) else got

    side = merge.load_sidecar()
    print(f"sidecar entries: {len(side):,}")

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="apply_pending_board_fills")
    with lock:
        listings = load_board(REPO / "docs")
        before = len(listings)
        print(f"board rows: {before:,}\n")

        # ---- 1. liensnc related-filings sidecar ----
        m = Counter()
        hit: set = set()
        for li in listings:
            raw = li.raw if isinstance(li.raw, dict) else {}
            ln = raw.get("liensnc") if isinstance(raw.get("liensnc"), dict) else {}
            ent = str(ln.get("entry_number") or "").strip()
            if not ent or ent not in side:
                continue
            rec = side[ent]
            m["matched"] += 1
            hit.add(ent)
            oc = rec.get("owner_contact") or {}
            fills_name = bool(oc.get("name")) and not (li.owner_name or "").strip()
            if fills_name:
                m["owner_name_filled"] += 1
            if oc.get("phone"):
                m["gains_owner_phone"] += 1
            if oc.get("mailing"):
                m["gains_owner_mailing"] += 1
            if int(rec.get("notice_count") or 0) >= 1:
                m["with_supplier_notice"] += 1
            if args.dry_run:
                continue
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["liensnc_related"] = {k: v for k, v in rec.items() if k != "entry_number"}
            if fills_name:
                li.owner_name = oc["name"]

        print("--- 1. liensnc related-filings merge ---")
        print(f"  matched board rows           : {m['matched']:,}")
        print(f"  from sidecar entries         : {len(hit):,} "
              f"({m['matched'] / max(len(hit), 1):.2f} board rows per entry)")
        print(f"  gain an owner PHONE          : {m['gains_owner_phone']:,}")
        print(f"  gain an owner MAILING        : {m['gains_owner_mailing']:,}")
        print(f"  owner_name filled where blank: {m['owner_name_filled']:,}")
        print(f"  >=1 supplier notice          : {m['with_supplier_notice']:,}")
        stranded = set(side) - hit
        if stranded:
            print(f"  sidecar entries with NO board row: {len(stranded):,} "
                  f"(entry left the board since capture)")

        # ---- 2. county typo / town repair ----
        how = Counter()
        by_src = Counter()
        samples = []
        for li in listings:
            cty = (li.county or "").strip()
            if not cty or repair.is_real(cty, li.state or ""):
                continue
            by_src[li.source or "?"] += 1
            new, method = repair.resolve(cty, li.state or "", li.city, city_lookup)
            how[method] += 1
            if len(samples) < 12:
                samples.append((cty, li.city, li.state, new, method))
            if args.dry_run:
                continue
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["county_repaired_from"] = cty
            li.county = new

        bad = sum(how.values())
        recovered = bad - how["cleared"]
        print("\n--- 2. county typo / town repair ---")
        print(f"  rows with a non-county county: {bad:,}")
        for meth, n in how.most_common(8):
            print(f"     {n:>6,}  {meth}")
        print(f"  RECOVERED to a real county   : {recovered:,}")
        print(f"  cleared (honest unknown)     : {how['cleared']:,}")
        for cty, city, st, new, meth in samples:
            print(f"     {cty[:24]!r:<26} city={str(city)[:16]:<18} {st} -> {new!r:<14} [{meth}]")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        assert len(listings) == before, "fills must not change the row count"
        write_artifact(listings, {
            "total": len(listings),
            "notes": (f"pending fills: liensnc_related on {m['matched']:,} rows "
                      f"({m['gains_owner_phone']:,} owner phones, "
                      f"{m['gains_owner_mailing']:,} mailings); "
                      f"county repair {recovered:,} recovered / {how['cleared']:,} cleared"),
            "off_footprint_removed": 0,
        }, docs_dir=REPO / "docs")
        print(f"\nwrote board: {before:,} rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
