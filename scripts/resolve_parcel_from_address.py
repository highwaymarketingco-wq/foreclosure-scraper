#!/usr/bin/env python3
"""Backfill parcel_id for court-record rows that have a street_address but no parcel.

WHY THIS EXISTS
    sc_public_index, liensnc, nc_ecourts_judgments and similar court/lien sources
    carry party names and often an address, but never a parcel number -- the court
    record doesn't have one. Board-wide this is thousands of rows: Anderson SC 1,364,
    Gaston NC 1,438, Laurens SC 853, Cherokee SC 703, Henderson NC 755 -- missing
    parcel_id, which blocks the value/mailing/absentee JOIN against the parcel cache
    even though the county's cache exists and is populated.

    Of those, hundreds to low-thousands per county already carry a street_address.
    An address IS a parcel key -- we already hold the parcel caches with an
    `address` column, just indexed by id, not address.

THE MATCH
    Reuses models._normalize_addr, the SAME canonicalizer dedupe.py uses, so a
    match here means the same normalization that already proved safe for merging
    board rows. Builds address -> {parcel_id} per county from the local cache
    (offline, no network) and commits ONLY when the normalized address maps to
    EXACTLY ONE parcel_id in that county. Same discipline as the name resolver:
    an address shared by multiple parcels (a subdivision's common area, multiple
    units at one street number recorded oddly) is left alone rather than guessed.

    python scripts/resolve_parcel_from_address.py --dry-run
    python scripts/resolve_parcel_from_address.py
"""
from __future__ import annotations

import argparse
import contextlib
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.models import _normalize_addr  # noqa: E402
from foreclosure_scraper.parcel_cache import _db_path  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


# An id used by more than this many DISTINCT addresses is not a parcel key, it is
# a placeholder/collision bucket -- see the Cumberland finding below.
_MAX_ADDRS_PER_ID = 3


def build_addr_index(county: str, state: str | None) -> tuple[dict[str, set[str]], set[str]]:
    """(normalized_address -> {parcel_id, ...}, set of POISONED ids) for one cache.

    THE BUG THIS GUARDS AGAINST. Cumberland's cache has id "37051" attached to
    6,886 rows carrying 6,102 DISTINCT addresses -- a placeholder id some upstream
    id_fields mapping fell back to, not a real parcel. Naive address->id matching
    "succeeds" on every one of those rows: each address STRING is unique in the
    data (ordinary text), so the forward index [address -> {id}] always has
    len==1 per row and never looks ambiguous. The corruption is only visible from
    the OTHER direction -- one id, thousands of addresses -- which forward
    uniqueness checks alone never see. Found live 2026-09-14: the first ten
    "resolved" matches out of a first pass all pointed at this single poisoned id.
    Not unique to Cumberland: Henderson (196 addresses/id) and Mecklenburg (170)
    show the same pattern at smaller scale, including in-footprint counties.

    So an id is disqualified if it is attached to more than _MAX_ADDRS_PER_ID
    distinct addresses, REGARDLESS of whether any single address maps to it
    uniquely. Small numbers (2-3) are legitimate -- a rebuilt/re-platted parcel
    can carry both an old and current situs -- large numbers are not.
    """
    try:
        p = _db_path(county, state)
    except ValueError:
        return {}, set()
    if not p.exists():
        return {}, set()
    idx: dict[str, set[str]] = defaultdict(set)
    id_addrs: dict[str, set[str]] = defaultdict(set)
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        for pid, addr in con.execute(
                "SELECT id, address FROM parcels WHERE address IS NOT NULL AND address <> ''"):
            k = _normalize_addr(addr)
            if k:
                idx[k].add(pid)
                id_addrs[pid].add(k)
    except sqlite3.OperationalError:
        return {}, set()
    finally:
        con.close()
    poisoned = {pid for pid, addrs in id_addrs.items() if len(addrs) > _MAX_ADDRS_PER_ID}
    return idx, poisoned


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="addr_resolve")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows: {before:,}")

        targets = [li for li in rows
                   if not li.parcel_id and (li.street_address or "").strip() and li.county]
        print(f"unresolved leads carrying a street_address: {len(targets):,}")

        by_county: dict[tuple[str, str | None], list] = defaultdict(list)
        for li in targets:
            by_county[(li.county, li.state)].append(li)

        c = Counter()
        examples: list[str] = []
        for (county, state), leads in sorted(by_county.items(), key=lambda kv: -len(kv[1])):
            idx, poisoned = build_addr_index(county, state)
            if not idx:
                c["no cache for county"] += len(leads)
                continue
            if poisoned:
                c["poisoned ids excluded from this county"] += len(poisoned)
            for li in leads:
                k = _normalize_addr(li.street_address)
                if not k:
                    c["address too thin to key"] += 1
                    continue
                hits = (idx.get(k) or set()) - poisoned
                if not hits:
                    if idx.get(k):
                        c["only match was a POISONED id (left alone)"] += 1
                    else:
                        c["no address match"] += 1
                elif len(hits) > 1:
                    c["AMBIGUOUS (left alone)"] += 1
                else:
                    pid = next(iter(hits))
                    c["RESOLVED"] += 1
                    if len(examples) < 10:
                        examples.append(f"{county},{state}  {li.street_address[:34]:36} -> {pid}")
                    if not args.dry_run:
                        li.parcel_id = pid

        print()
        for k, v in c.most_common():
            if v:
                print(f"  {k:28} {v:,}")
        print("\nexamples:")
        for e in examples:
            print("   ", e)

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        assert len(rows) == before, "row count changed — refusing to write"
        write_artifact(rows, {"addr_resolved_parcel": c["RESOLVED"]}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows unchanged, {c['RESOLVED']:,} parcel_ids resolved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
