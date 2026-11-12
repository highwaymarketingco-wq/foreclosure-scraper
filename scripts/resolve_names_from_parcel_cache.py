#!/usr/bin/env python3
"""Resolve a lead's PARTY NAME to a property using the local parcel caches.

WHY THIS EXISTS
    The NC statutory foreclosure notices carry a defendant name and an SP case
    number but no address and no sale date — the full body is behind a reCAPTCHA
    gate, so only the ~300-char preview parses. 622 such leads are on the board.

    The existing resolver (resolve_court_names_dryrun) cannot help: it reads
    `owner_name` (these carry the name in `defendant`) and it has NO NC endpoints
    wired, only five SC layers.

    But we already hold 103 county parcel caches, and the NC ones carry an owner
    name on essentially every parcel (Buncombe 398,939/398,939). So the match can
    be done LOCALLY, offline, with no GIS call at all.

NAME SHAPES
    A parcel layer writes the owner LAST-FIRST ("LEWIS NANCY GAIL"); a court notice
    writes the party FIRST-LAST ("NANCY GAIL LEWIS"). Comparing the strings fails.
    Both are reduced to a sorted TOKEN SET, which is order-free.

WHY UNIQUENESS IS REQUIRED
    "SMITH JOHN" matches hundreds of parcels in one county. Committing any of them
    would attach a real person's foreclosure to a stranger's house. A name is
    resolved ONLY when it matches exactly ONE parcel in that county; everything
    else is reported as ambiguous and left alone.

    python scripts/resolve_names_from_parcel_cache.py --dry-run
    python scripts/resolve_names_from_parcel_cache.py
"""
from __future__ import annotations

import argparse
import contextlib
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.parcel_cache import CACHE_DIR, DUAL_STATE_COUNTIES, _db_path  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

# Suffixes and entity words that carry no identifying power.
_NOISE = {"jr", "sr", "ii", "iii", "iv", "v", "mr", "mrs", "ms", "dr",
          "etal", "et", "al", "the", "and", "of"}
_PUNCT = re.compile(r"[^a-z\s]")


def name_key(name: str) -> tuple[str, ...] | None:
    """Order-free key for a personal name, or None if too thin to be safe."""
    if not name:
        return None
    toks = [t for t in _PUNCT.sub(" ", name.lower()).split() if t and t not in _NOISE]
    toks = [t for t in toks if len(t) > 1]
    # One token is a surname alone ("SMITH") — far too broad to match on.
    if len(toks) < 2:
        return None
    return tuple(sorted(set(toks)))


def build_index(county: str, state: str | None) -> dict[tuple[str, ...], list[tuple]]:
    """owner-name key -> [(parcel_id, address, owner)] for one county cache."""
    try:
        p = _db_path(county, state)
    except ValueError:
        return {}
    if not p.exists():
        return {}
    idx: dict[tuple[str, ...], list[tuple]] = defaultdict(list)
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        for pid, owner, addr in con.execute(
                "SELECT id, owner, address FROM parcels WHERE owner IS NOT NULL AND owner <> ''"):
            k = name_key(owner)
            if k:
                idx[k].append((pid, addr, owner))
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()
    return idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="name_resolve")
    with lock:
        rows = load_board(REPO / "docs")
        before = len(rows)
        print(f"board rows: {before:,}")

        targets = [li for li in rows
                   if not (li.street_address or "").strip()
                   and (li.defendant or li.owner_name)
                   and li.county]
        if args.limit:
            targets = targets[:args.limit]
        print(f"unresolved leads carrying a name: {len(targets):,}")

        by_county: dict[tuple[str, str | None], list] = defaultdict(list)
        for li in targets:
            by_county[(li.county, li.state)].append(li)

        c = Counter()
        examples: list[str] = []
        for (county, state), leads in sorted(by_county.items(),
                                             key=lambda kv: -len(kv[1])):
            idx = build_index(county, state)
            if not idx:
                c["no cache for county"] += len(leads)
                continue
            c["counties with a cache"] += 0
            for li in leads:
                k = name_key(li.defendant or li.owner_name or "")
                if not k:
                    c["name too thin to match"] += 1
                    continue
                hits = idx.get(k) or []
                if not hits:
                    c["no owner match"] += 1
                elif len(hits) > 1:
                    c["AMBIGUOUS (left alone)"] += 1
                else:
                    pid, addr, owner = hits[0]
                    # Count these apart. A unique owner match with NO address in the
                    # cache still yields a parcel_id (joinable to value/mailing), but
                    # it is not an address and must not be reported as one.
                    # "0 SHERWOOD PL" is a vacant-land placeholder, not a mailable
                    # address, and the board write path strips it (verified: ZERO board
                    # rows carry an address starting "0 "). Counting it as an address
                    # overstated this resolver by 4x on its first run — 344 claimed,
                    # 82 actually landed. Count what the pipeline will keep.
                    usable = bool((addr or "").strip()) and not re.match(r"^0\s", addr.strip())
                    if usable:
                        c["RESOLVED (usable address)"] += 1
                    else:
                        c["parcel only (no usable address)"] += 1
                    c["RESOLVED"] += 1
                    if len(examples) < 8:
                        examples.append(
                            f"{county},{state}  {(li.defendant or li.owner_name)[:26]:28}"
                            f"-> {str(addr)[:30]:32} [{pid}]")
                    if not args.dry_run:
                        if usable:
                            li.street_address = addr
                        if not li.parcel_id:
                            li.parcel_id = pid
                        if not li.owner_name:
                            li.owner_name = owner
                        blk = li.raw.setdefault("name_resolution", {}) if isinstance(li.raw, dict) else None
                        if blk is not None:
                            blk.update({"matched_owner": owner, "parcel_id": pid,
                                        "method": "parcel_cache_unique_token_set"})

        print()
        for k, v in c.most_common():
            if v:
                print(f"  {k:28} {v:,}")
        n = c["RESOLVED"] + c["AMBIGUOUS (left alone)"] + c["no owner match"]
        if n:
            print(f"\n  resolution rate: {100*c['RESOLVED']//n}% of names checked against a cache")
        print("\nexamples:")
        for e in examples:
            print("   ", e)

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0
        assert len(rows) == before, "row count changed — refusing to write"
        write_artifact(rows, {"name_resolved": c["RESOLVED"]}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows unchanged, {c['RESOLVED']:,} resolved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
