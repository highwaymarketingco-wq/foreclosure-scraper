#!/usr/bin/env python3
"""Second pass on address->parcel: FUZZY street match, same house number required.

WHY A SECOND PASS
    resolve_parcel_from_address.py does an EXACT normalized-address match and
    left 21,965 board rows with a street_address unmatched. Many of those are
    real misses against data we already hold, not absent data: a court record
    writes "1234 N Main Street Apt 2" where the cache has "1234 MAIN ST", or a
    typo, or a missing directional. The county's own parcel cache already has
    the answer; the exact-match pass just couldn't see it.

THE SAFETY MODEL
    A different house number is essentially always a different property (the
    same rule dedupe.py's _provably_different_property proved out on this board:
    "306 fountain way" and "346 fountain way" are NOT the same house). So the
    house number is a HARD GATE, not part of the fuzzy score: candidates are
    first bucketed by exact house number (cheap, and it is where the real
    safety lives), and ONLY the street-name remainder is fuzzy-compared within
    that bucket. A candidate pool is rejected outright if it is poisoned (see
    the exact-match script) or if more than one candidate clears the similarity
    threshold -- ambiguous stays unresolved rather than guessed.

    Threshold 92 matches dedupe.py's own pass-2 fuzzy address threshold, chosen
    there as the point live-tested to separate real matches from false ones.

    python scripts/resolve_parcel_from_address_fuzzy.py --dry-run
    python scripts/resolve_parcel_from_address_fuzzy.py
"""
from __future__ import annotations

import argparse
import contextlib
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

from rapidfuzz import fuzz

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.models import _normalize_addr  # noqa: E402
from foreclosure_scraper.parcel_cache import _db_path  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

_MAX_ADDRS_PER_ID = 3
_THRESHOLD = 92


def _house_no(addr: str) -> str:
    m = re.match(r"\s*(\d+)\b", (addr or "").strip())
    return m.group(1) if m else ""


def _street_remainder(normalized: str, house_no: str) -> str:
    """The normalized address with its own house number stripped, for the fuzzy
    compare -- comparing "1234 main st" to "1234 n main st" should score on
    "main st" vs "n main st", not be diluted by the (already-matching) number."""
    if house_no and normalized.startswith(house_no):
        return normalized[len(house_no):].strip()
    return normalized


def build_index(county: str, state: str | None):
    """house_number -> [(street_remainder, parcel_id), ...], POISONED id set."""
    try:
        p = _db_path(county, state)
    except ValueError:
        return None, set()
    if not p.exists():
        return None, set()
    by_house: dict[str, list[tuple[str, str]]] = defaultdict(list)
    id_addrs: dict[str, set[str]] = defaultdict(set)
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        for pid, addr in con.execute(
                "SELECT id, address FROM parcels WHERE address IS NOT NULL AND address <> ''"):
            k = _normalize_addr(addr)
            if not k:
                continue
            hn = _house_no(k)
            if not hn:
                continue
            by_house[hn].append((_street_remainder(k, hn), pid))
            id_addrs[pid].add(k)
    except sqlite3.OperationalError:
        return None, set()
    finally:
        con.close()
    poisoned = {pid for pid, addrs in id_addrs.items() if len(addrs) > _MAX_ADDRS_PER_ID}
    return by_house, poisoned


def best_match(by_house, poisoned, addr: str) -> str | None:
    k = _normalize_addr(addr)
    hn = _house_no(k)
    if not hn or not by_house or hn not in by_house:
        return None
    remainder = _street_remainder(k, hn)
    if not remainder:
        return None
    scored = []
    for cand_street, pid in by_house[hn]:
        if pid in poisoned:
            continue
        s = fuzz.token_sort_ratio(remainder, cand_street)
        if s >= _THRESHOLD:
            scored.append((s, pid))
    if not scored:
        return None
    ids = {pid for _, pid in scored}
    if len(ids) > 1:
        return None  # ambiguous — multiple distinct parcels cleared the bar
    return next(iter(ids))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="addr_fuzzy")
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
            by_house, poisoned = build_index(county, state)
            if by_house is None:
                c["no cache for county"] += len(leads)
                continue
            for li in leads:
                pid = best_match(by_house, poisoned, li.street_address)
                if not pid:
                    c["no fuzzy match"] += 1
                    continue
                c["RESOLVED"] += 1
                if len(examples) < 10:
                    examples.append(f"{county},{state}  {li.street_address[:36]:38} -> {pid}")
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
        write_artifact(rows, {"addr_fuzzy_resolved": c["RESOLVED"]}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows unchanged, {c['RESOLVED']:,} parcel_ids resolved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
