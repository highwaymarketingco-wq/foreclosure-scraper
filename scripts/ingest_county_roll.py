#!/usr/bin/env python3
"""Load a county assessor/auditor roll file (public-records request) into the parcel cache.

    python scripts/ingest_county_roll.py --county Williamsburg --state SC \\
        --file ~/Desktop/Records_Requests/Received/SC_Williamsburg_roll_2026-11-03.csv --dry-run
    python scripts/ingest_county_roll.py --county Williamsburg --state SC --file <path> [--file <path2>]
    python scripts/ingest_county_roll.py ... --map roll_maps/williamsburg.json --report

Reads CSV / TSV / pipe / semicolon text, fixed-width text, .xlsx, or a .zip holding one of those
(foreclosure_scraper.county_roll). Drops every SSN / driver-licence / birth-date column before any
value is read. Auto-detects the common column names; --map is a small JSON override, e.g.

    {"id": ["PIN", "ACCOUNT"], "owner1": "OWNER NAME", "mail_street": "ADDR 1",
     "mail_city": "CITY", "mail_state": "ST", "mail_zip": "ZIP",
     "fixed_width": [["PIN", 0, 14], ["OWNER NAME", 14, 54]]}

Roles: id (list), owner1, owner2, mail_single, mail_street, mail_street2, mail_city, mail_state,
mail_zip, mail_citystatezip, situs, situs_num, situs_street, land_use, market_value, tax_value,
acreage, living_sqft, year_built, bedrooms, baths_full, baths_half, stories, sale_price, sale_date.

--dry-run   prints the detected mapping (header -> role) and per-column fill counts, writes nothing.
(default)   writes data/parcel_cache/<county>.roll.sqlite atomically (provenance
            county_roll_request + the file's date). Re-running the same file gives the same
            sidecar; the weekly layer refresh never touches it.
--report    after writing, one streaming pass of the board per state of the sidecar: rows in the
            county the cache join would fill, without and with the roll. Counts only.
--cache-dir write/read the cache somewhere else (tests and synthetic demos).

Prints counts and header names only: never owner names, addresses or ids.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from foreclosure_scraper import county_roll as cr  # noqa: E402
from foreclosure_scraper import parcel_cache as pc  # noqa: E402


def board_report(county: str, state: str, board: str) -> dict:
    """{'before': counts, 'after': counts} for the county: what the join fills with the layer
    cache alone, and with the roll sidecar too."""
    from foreclosure_scraper.board_stream import iter_board_rows
    from measure_cache_facts_lift import measure
    key = f"{state}:{county}"
    real = pc.roll_db_path
    pc._CONN.clear()
    pc._CONN_COLS.clear()
    try:
        pc.roll_db_path = lambda *a, **k: Path("/nonexistent/none.roll.sqlite")
        before = measure(iter_board_rows(board), {key}).get(key, {})
    finally:
        pc.roll_db_path = real
    pc._CONN.clear()
    pc._CONN_COLS.clear()
    after = measure(iter_board_rows(board), {key}).get(key, {})
    return {"before": before, "after": after}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--county", required=True)
    ap.add_argument("--state", required=True, choices=["SC", "NC", "sc", "nc"])
    ap.add_argument("--file", required=True, action="append", help="roll file (repeatable)")
    ap.add_argument("--map", help="per-county mapping JSON override")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--board", default=str(REPO / "docs" / "listings.json.gz"))
    ap.add_argument("--cache-dir")
    a = ap.parse_args(argv)

    state = a.state.upper()
    county = cr.canonical_county(a.county, state)
    if a.cache_dir:
        pc.CACHE_DIR = Path(a.cache_dir)
    override = cr.load_override(a.map)

    merged = cr.RollRecords(rows=[], stats={})
    seen: set[str] = set()
    prov_date = None
    for f in a.file:
        headers, body, fmt = cr.read_table(f, override=override)
        dropped = [h for h in headers if h and h not in cr.safe_headers(headers)]
        mapping = cr.detect_mapping(headers, override)
        recs = cr.build_records(headers, body, mapping)
        print(f"{Path(f).name}: format {fmt}, {len(headers)} columns, {recs.stats.get('rows', 0):,} rows")
        if dropped:
            print(f"  sensitive columns dropped unread: {len(dropped)} ({', '.join(dropped)})")
        print("  mapping (role <- header):")
        for role, h in sorted(mapping.roles.items()):
            if h:
                print(f"    {role:18} <- {h}")
        unmapped = [h for h in cr.safe_headers(headers)
                    if h not in {x for v in mapping.roles.values() for x in (v if isinstance(v, list) else [v])}]
        print(f"  unmapped columns: {len(unmapped)}")
        st = recs.stats
        print(f"  rows with an id {st.get('rows_with_id', 0):,}; parcels indexed {st.get('parcels_indexed', 0):,}")
        print("  fill counts per cache column: " + ", ".join(
            f"{c} {st.get(c, 0):,}" for c in pc._COLS if st.get(c)))
        for row in recs.rows:
            if row[0] not in seen:
                seen.add(row[0])
                merged.rows.append(row)
        d = cr.file_date(f)
        prov_date = max(prov_date or d, d)
    if a.dry_run:
        print("\nDRY RUN: nothing written.")
        return 0
    if not merged.rows:
        print("no row carried a parcel id: nothing written (check --map 'id').")
        return 1
    path = cr.write_roll(county, state, merged, prov_date)
    print(f"\nwrote {path} ({len(merged.rows):,} id keys, prov {pc.ROLL_PROVENANCE} {prov_date})")
    if a.report:
        rep = board_report(county, state, a.board)
        for f in ("mailing", "year_built", "bedrooms", "bathrooms", "living_sqft", "last_sale", "market_value"):
            b = rep["before"].get(f + "_fill", 0)
            af = rep["after"].get(f + "_fill", 0)
            print(f"  {f:13} board rows filled: without roll {b:,}  with roll {af:,}")
        print(f"  board rows in county {rep['after'].get('rows', 0):,}; with parcel id "
              f"{rep['after'].get('parcel_id', 0):,}; roll hits {rep['after'].get('roll_hit', 0):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
