#!/usr/bin/env python3
"""Stamp flip-type leads that sit outside the 18-county footprint so the scorer can exclude them.

OWNER RULE (2026-09-15, main._FLIP_LISTING_TYPES): a FLIP (foreclosure_sale, auction, sheriff_sale,
hoa_sale, reo: something you could bid on or buy today) is only in the 18 footprint counties
(config.SC_COUNTIES + NC_COUNTIES). A distressed LEAD (tax, lien, probate ...) is anywhere in NC+SC.

Audit 2026-09-21 section 9: 102 flip rows sit outside the 18 counties (Charleston 33, Pender 24,
Georgetown 15, Dare 11, Onslow 7, Carteret 6 ...) plus 21 REO rows with no county. WHY THEY GOT IN is
in docs/data_quality_fixes_2026-09-21.md (main._in_scope admits coastal / oceanfront / downtown
Charleston rows BEFORE the flip footprint check, and _denied_now exempts them again).

THIS SCRIPT MOVES NOTHING. It never drops, deletes or edits a lead's fields. It stamps
raw['scope'] = 'flip_outside_footprint', and the scorer reads that stamp (handoff note in the doc) to keep
the lead out of HOT and WARM. It is idempotent and self-correcting: a row stamped earlier whose county
is now inside the footprint (or that is no longer a flip) has the stamp removed.

A flip with NO county is judged by the county scripts/backfill_missing_county.py would give it (same
evidence, same rules), and stamped only when that county is unambiguous and outside the footprint;
otherwise it is left alone and counted, so run the county backfill first.

    python scripts/quarantine_flip_leaks.py            # dry run: counts by source / county / admission path
    python scripts/quarantine_flip_leaks.py --apply    # ONLY board process (about 3 GB)
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dq_common import (FLIP_TYPES, footprint, iter_rows, lt_str, norm_county,  # noqa: E402
                        print_counter)

STAMP = "flip_outside_footprint"


def flip_verdict(state, county, listing_type, footprint_set=None) -> str:
    """'leak' (a flip whose county is known and is outside the footprint), 'in_footprint',
    'no_county' (a flip we cannot judge), or 'not_flip'."""
    if lt_str(listing_type) not in FLIP_TYPES:
        return "not_flip"
    c = norm_county(county)
    if not c or c.lower() == "statewide":
        return "no_county"
    fp = footprint_set if footprint_set is not None else footprint()
    return "in_footprint" if (str(state or "").upper(), c.lower()) in fp else "leak"


def admission_path(source, state, county, lat, lng, city) -> str:
    """Which main._in_scope branch let this flip in (root-cause attribution, best effort)."""
    try:
        from foreclosure_scraper import main as M
    except Exception:  # noqa: BLE001
        return "unknown"
    c = norm_county(county).title()
    key = (c, str(state or "").upper())
    if not c:
        return "no_county (zip-prefix fallback or ingest script that skips the re-pass)"
    if source in M.COASTAL_COUNTY_BYPASS_SOURCES and key in M.OCEANFRONT_COASTAL_COUNTIES:
        return "COASTAL_COUNTY_BYPASS_SOURCES (all listing types admitted)"
    try:
        a0, a1, o0, o1 = M.DOWNTOWN_CHARLESTON_BBOX
        if key == ("Charleston", "SC") and lat is not None and lng is not None \
                and a0 <= float(lat) <= a1 and o0 <= float(lng) <= o1 \
                and (city or "").strip().lower() not in M._DOWNTOWN_CHS_DENY_CITY:
            return "downtown Charleston bbox"
    except (TypeError, ValueError):
        pass
    if key in M.OCEANFRONT_COASTAL_COUNTIES:
        return "oceanfront override / oceanfront_pending / _denied_now coastal carve-out"
    return "other"


def _derive_county(ev, state, zip_code, city, parcel_id):
    r = ev.resolve(state, zip_code, city, parcel_id)
    return r["county"] if r["status"] == "resolved" else None


# --------------------------------------------------------------------------------------- dry run
def _dry_run(rows_file=None, derive=True, board_agg=None) -> int:
    fp = footprint()
    ev = None
    if derive:
        import backfill_missing_county as B
        ev = B.Evidence()
        ev.build_from_caches()
        if board_agg:
            import json
            agg = json.load(open(board_agg))
            for k, v in agg["zip_county"].items():
                ev.board_zip[k].update(v)
            for k, v in agg["city_county"].items():
                ev.board_city[k].update(v)
    leaks = []
    nocounty = []
    n = flips = already = 0
    for r in iter_rows(rows_file):
        n += 1
        if ev is not None and not board_agg and norm_county(r.get("county")):
            ev.add_board_row(r.get("state"), r.get("county"), r.get("zip_code"), r.get("city"))
        v = flip_verdict(r.get("state"), r.get("county"), r.get("listing_type"), fp)
        stamped = (r.get("raw") or {}).get("scope") == STAMP
        if v != "not_flip":
            flips += 1
        if stamped:
            already += 1
        row = (r.get("source"), str(r.get("state") or "").upper(), norm_county(r.get("county")), lt_str(r.get("listing_type")),
               r.get("latitude"), r.get("longitude"), r.get("city"), r.get("zip_code"), r.get("parcel_id"), stamped)
        if v == "leak":
            leaks.append(row)
        elif v == "no_county":
            nocounty.append(row)
    print(f"board rows scanned: {n:,}; flip-type rows: {flips:,}; already stamped: {already:,}")
    print(f"\nFLIP ROWS OUTSIDE THE 18-COUNTY FOOTPRINT (county known): {len(leaks):,}")
    by_src, by_cty, by_path, by_type = Counter(), Counter(), Counter(), Counter()
    for src, st, co, lt, lat, lng, city, _z, _p, _s in leaks:
        by_src[str(src)] += 1
        by_cty[f"{st} {co}"] += 1
        by_type[lt] += 1
        by_path[admission_path(src, st, co, lat, lng, city)] += 1
    print_counter(by_src, "by source")
    print_counter(by_cty, "by county")
    print_counter(by_type, "by listing type")
    print_counter(by_path, "by main._in_scope admission path")
    print(f"\nFLIP ROWS WITH NO COUNTY: {len(nocounty):,}")
    nc = Counter()
    for src, st, _co, lt, _la, _ln, city, z, pid, _s in nocounty:
        if ev is None:
            nc["not judged (--no-derive)"] += 1
            continue
        d = _derive_county(ev, st, z, city, pid)
        if d is None:
            nc["county not derivable: left alone"] += 1
        elif (st, d.lower()) in fp:
            nc[f"derived {d}: inside the footprint, no stamp"] += 1
        else:
            nc[f"derived {d}: OUTSIDE the footprint, would stamp"] += 1
    print_counter(nc)
    would = len(leaks) + sum(v for k, v in nc.items() if "would stamp" in k)
    print(f"\nWOULD STAMP raw['scope']='{STAMP}': {would:,} rows (no field is changed, no row is removed)")
    print("DRY RUN, nothing written. Re-run with --apply (as the only board process).")
    return 0


# ----------------------------------------------------------------------------------------- apply
REQUIRED_RAW_KEYS = ["scope"]
BACKUP_NAME = "quarantine_flip_leaks"


def apply_rows(rows: list, *, dry_run: bool = False, derive_county: bool = False, evidence=None) -> dict:
    """Stamp / clear raw['scope'] on Listing objects, in place. Never changes len(rows) and never writes a
    file. derive_county=True also judges county-less flips by the evidence backfill_missing_county uses (pass
    `evidence` to share its cache scan); in a chain, run backfill_missing_county FIRST and leave it False.
    dry_run=True mutates nothing."""
    from _dq_common import assert_raw_keep
    if not dry_run:
        assert_raw_keep(REQUIRED_RAW_KEYS)
    n = len(rows)
    fp = footprint()
    ev = evidence
    if derive_county and ev is None:
        import backfill_missing_county as B
        ev = B.build_evidence(rows)
    c: Counter = Counter()
    for li in rows:
        v = flip_verdict(li.state, li.county, li.listing_type, fp)
        leak = v == "leak"
        if v == "no_county":
            d = _derive_county(ev, li.state, li.zip_code, li.city, li.parcel_id) if ev is not None else None
            leak = bool(d) and (str(li.state or "").upper(), d.lower()) not in fp
            c["no-county flip: county derived" if d else "no-county flip: not derivable, left alone"] += 1
        raw = li.raw if isinstance(li.raw, dict) else None
        stamped = bool(raw) and raw.get("scope") == STAMP
        if leak:
            if stamped:
                c["already stamped"] += 1
            else:
                c["stamped"] += 1
                if not dry_run:
                    if raw is None:
                        li.raw = raw = {}
                    raw["scope"] = STAMP
        elif stamped:
            c["stamp cleared (now in footprint or not a flip)"] += 1
            if not dry_run:
                raw.pop("scope", None)
    assert len(rows) == n, "a quarantine must never change the row count"
    return {k: v for k, v in c.items() if v}


def _apply(derive=True) -> int:
    from _dq_common import run_apply
    return run_apply("quarantine_flip_leaks", lambda rows, dry_run=False: apply_rows(rows, dry_run=dry_run, derive_county=derive),
                     REQUIRED_RAW_KEYS, BACKUP_NAME)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the board (ONLY board process)")
    ap.add_argument("--rows-file", help="dry run over a saved JSONL extract instead of the live board")
    ap.add_argument("--board-agg", help="with --rows-file: JSON of full-board zip/city county counters")
    ap.add_argument("--no-derive", action="store_true", help="do not judge county-less flips")
    args = ap.parse_args()
    if not args.apply:
        return _dry_run(args.rows_file, not args.no_derive, args.board_agg)
    if args.rows_file:
        raise SystemExit("--rows-file is dry-run only")
    return _apply(not args.no_derive)


if __name__ == "__main__":
    raise SystemExit(main())
