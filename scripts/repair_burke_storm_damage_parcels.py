#!/usr/bin/env python3
"""Replace junk record numbers in Burke storm-damage parcel_id with real parcels.

Found 2026-09-20: 397 `burke_storm_damage` leads (29% of Burke) carry a 3 to 5 digit
number in parcel_id, not a Burke PIN (10 digits). It is a damage-assessment record number.
The parcel-cache join cannot match it, so those leads have no owner, mailing or value, and
enrich_parcel_from_geo skips them because they already "have" a parcel_id. All 397 have
coordinates and 374 a street address.

The fix matches each lead's own STREET ADDRESS against the Burke parcel cache's situs
column (offline, no network) and accepts a lead only when exactly one Burke parcel has that
house number and a shared street word. Coordinates were tried first and rejected: in a live
sample of 25, 18 (72%) resolved by point-in-polygon to a parcel whose own address disagreed
with the lead's, because these leads' coordinates are approximate. A wrong parcel means the
wrong owner and mailing address, so the address must agree by construction. The replaced
record numbers are kept in backups/ so nothing is lost. Leads with no street address,
no matching parcel, or more than one candidate are left as they are.

    python scripts/repair_burke_storm_damage_parcels.py             # counts only: offline, no network, no writes
    python scripts/repair_burke_storm_damage_parcels.py --apply     # ONLY board process

After --apply run scripts/join_parcel_cache_to_board.py (fills owner, mailing, value from
the cache) and then recompute_valuation + rank_board_standalone.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

JUNK_MAX_DIGITS = 6
_STOP = {"ST", "STREET", "RD", "ROAD", "DR", "DRIVE", "LN", "LANE", "AVE", "AVENUE", "CT", "COURT",
         "CIR", "CIRCLE", "HWY", "HIGHWAY", "BLVD", "WAY", "PL", "PLACE", "TRL", "TRAIL", "N", "S", "E", "W",
         "NE", "NW", "SE", "SW", "NORTH", "SOUTH", "EAST", "WEST", "NC", "US"}


def is_junk_burke_id(source, state, county, parcel_id) -> bool:
    """A storm-damage lead whose parcel_id is a short record number, not a Burke PIN."""
    if "burke_storm_damage" not in str(source or ""):
        return False
    if (state or "").upper() != "NC" or (county or "").replace(" County", "").strip() != "Burke":
        return False
    pid = (parcel_id or "").strip()
    return pid.isdigit() and len(pid) <= JUNK_MAX_DIGITS


def _street_parts(s) -> tuple[str, set]:
    """(house number, set of street-name words) from a street address, upper-cased."""
    toks = re.findall(r"[A-Z0-9]+", str(s or "").upper())
    num = next((t for t in toks if t.isdigit()), "")
    words = {t for t in toks if not t.isdigit() and t not in _STOP and len(t) > 1}
    return num, words


def addresses_agree(lead_street, cache_situs) -> bool:
    """Same house number and at least one shared street word. Both must be present."""
    n1, w1 = _street_parts(lead_street)
    n2, w2 = _street_parts(cache_situs)
    return bool(n1 and n2 and n1 == n2 and (w1 & w2))


def _candidates_dry(rows):
    c: Counter = Counter()
    for r in rows:
        if not is_junk_burke_id(r.get("source"), r.get("state"), r.get("county"), r.get("parcel_id")):
            continue
        c["junk-id storm-damage leads"] += 1
        if (r.get("street_address") or "").strip():
            c["  with street address"] += 1
        if r.get("latitude") and r.get("longitude"):
            c["  with coordinates"] += 1
    return c


def _canon_pin(pid: str) -> str:
    """The cache indexes each parcel as a 10-digit PIN and a 15-digit padded form."""
    pid = str(pid or "")
    return pid[:10] if len(pid) == 15 and pid.endswith("00000") else pid


def resolve_by_address(con, street) -> tuple[str, str | None]:
    """(status, pin). status: 'unique' | 'ambiguous' | 'none' | 'no_street'.
    Uses only parcels whose situs agrees with the street (house number + a shared word)."""
    num, _words = _street_parts(street)
    if not num:
        return "no_street", None
    pins: dict[str, str] = {}
    for pid, situs in con.execute("SELECT id, address FROM parcels WHERE address LIKE ?", (f"{num} %",)):
        if addresses_agree(street, situs):
            canon = _canon_pin(pid)
            if canon.isdigit() and len(canon) == 10:
                pins[canon] = situs
    if not pins:
        return "none", None
    if len(pins) > 1:
        return "ambiguous", None
    return "unique", next(iter(pins))


def _connect():
    import sqlite3
    from foreclosure_scraper import parcel_cache as pc
    return sqlite3.connect(f"file:{pc._db_path('Burke')}?mode=ro", uri=True)


def _dry_run() -> int:
    from foreclosure_scraper.board_stream import iter_board_rows
    rows = [r for r in iter_board_rows()
            if is_junk_burke_id(r.get("source"), r.get("state"), r.get("county"), r.get("parcel_id"))]
    for k, n in sorted(_candidates_dry(rows).items()):
        print(f"  {n:5,}  {k}")
    con = _connect()
    c: Counter = Counter()
    for r in rows:
        c["by street address: " + resolve_by_address(con, r.get("street_address"))[0]] += 1
    print()
    for k, n in sorted(c.items()):
        print(f"  {n:5,}  {k}")
    print("\nDRY RUN, nothing written, no network. Re-run with --apply (as the only board process).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        return _dry_run()

    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact

    with board_lock(REPO, owner="repair_burke_storm_damage_parcels"):
        rows = load_board(REPO / "docs")
        n = len(rows)
        cands = [li for li in rows if is_junk_burke_id(li.source, li.state, li.county, li.parcel_id)]
        con = _connect()
        stash, status = {}, Counter()
        for i, li in enumerate(cands):
            st, pin = resolve_by_address(con, li.street_address)
            status[st] += 1
            if st != "unique":
                continue
            # Keep the replaced record number so nothing is lost.
            stash[str(i)] = {"street": li.street_address, "old_parcel_id": li.parcel_id, "new_pin": pin}
            li.parcel_id = pin
            if isinstance(li.raw, dict):
                li.raw["parcel_from_geo"] = {"source": "burke_cache_situs_address", "verified": "address_exact"}
        if stash:
            (REPO / "backups").mkdir(exist_ok=True)
            (REPO / "backups" / f"burke_storm_damage_record_ids_{time.strftime('%Y%m%d')}.json").write_text(json.dumps(stash))
        assert len(rows) == n
        print(f"board rows: {n:,}; junk-id leads: {len(cands):,}; {dict(status)}", flush=True)
        write_artifact(rows, {"repair_burke_storm_damage_parcels": dict(status)}, docs_dir=REPO / "docs")
        print(f"resolved {status['unique']:,}; wrote board: {n:,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
