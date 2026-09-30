#!/usr/bin/env python3
"""Clean up the ~1,361 genuine duplicate rows found by board_selfcheck.py's "no duplicate
identifiable properties" invariant, using merge_duplicate_rows() (commit 6719e6bd) -- the
memory-safe follow-up to append_new_rows()/patch_existing_rows() built specifically for this,
never run against the real board before tonight.

WHY THE SURVIVOR RULE IS STRICTER THAN THE COMMIT MESSAGE ASSUMED. The commit's docstring
frames this as a single "mailing address vs situs address" pattern (arcgis_distress vs
multi_year_delinquent_tax on Buncombe). A read-only audit of the REAL 1,213 candidate groups
(same-parcel_id groups with <4 distinct addresses -- board_selfcheck.py's own FUSION_THRESHOLD)
found that pattern is a minority. Most 2-address groups under one parcel_id are two GENUINELY
DIFFERENT street addresses (different roads entirely, or same road but not obviously the same
structure), which merging would silently conflate into one lead -- real data loss, not cleanup.
One group (parcel:cleveland:17925) had 4 rows with different case numbers, different sale
dates, and different addresses under one parcel_id -- clearly an upstream parcel_id collision,
not a duplicate.

So this script only merges a group when the group is unambiguous by address:
  SAFE   = every row in the group agrees on exactly ONE non-blank normalized street address
           (rows with a blank address are folded into whichever row(s) carry the real one).
  SKIPPED = zero non-blank addresses anywhere in the group (can't confirm identity at all --
           several of these were parcel_ids shared by 8-16 rows, all address-less, which reads
           as a placeholder parcel_id, not a genuine single property), OR 2+ distinct non-blank
           addresses (ambiguous -- see above).
  Also skipped: a group where the identity hash collides between two of its own rows (an
  address-identical near-duplicate whose _MERGE_HASH_FIELDS subset matches byte-for-byte --
  merge_duplicate_rows()'s own contract requires a hash to resolve to exactly one row, so a
  self-colliding group cannot be expressed as a merge_groups entry at all).

Kept-row tie-break (when 2+ rows carry the one agreed address): the row with more populated
raw keys + core fields (case_number/opening_bid/sale_date/owner_name/owner_phone) is kept, per
merge_duplicate_rows()'s own guidance that the caller should pick "the copy with the correct
[...] address" as index 0 -- since address is tied here, completeness is the next best signal.

BOUNDED MEMORY. Never materializes the whole ~220k-row board as a Python list (that was tried
first tonight and killed at 2.3GB physical footprint and still climbing after 9s -- board_
selfcheck.py's `_current()` does exactly that and its "~290MB peak" comment does not hold on
this board's current size). This script's own audit passes are two BOUNDED streaming passes
(pass 1: identifier+address strings only, ~200-300MB peak measured; pass 2: full rows retained
ONLY for the small candidate set, ~300-430MB peak measured) -- merge_duplicate_rows() itself
then does its own internal single streaming pass exactly as designed by 6719e6bd.

USAGE
    .venv/bin/python scripts/run_duplicate_merge_20260930.py --dry-run   # audit + plan only
    BOARD_MERGE_ALLOW_LARGE=1 .venv/bin/python scripts/run_duplicate_merge_20260930.py --execute
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, merge_duplicate_rows, row_identity_hash  # noqa: E402

DOCS = REPO / "docs"
FUSION_THRESHOLD = 4  # mirrors scripts/board_selfcheck.py's FUSION_THRESHOLD exactly


def identifier(rec: dict) -> str | None:
    """Verbatim logic from scripts/board_selfcheck.py::_identifier() -- kept in sync by hand
    rather than imported, so this script's import chain stays minimal for a memory-sensitive
    run. See that function's own docstring for why parcel_id-or-numbered-address is what
    actually names a property on this board."""
    r = rec or {}
    pid = str(r.get("parcel_id") or "").strip()
    if pid:
        return f"parcel:{(r.get('county') or '').lower()}:{pid.lower()}"
    addr = str(r.get("street_address") or "").strip()
    parts = addr.split()
    if parts and any(ch.isdigit() for ch in parts[0]):
        return f"addr:{(r.get('county') or '').lower()}:{addr.lower()}"
    return None


def norm_addr(a) -> str:
    a = str(a or "").strip().upper()
    a = re.sub(r"[^A-Z0-9 ]", " ", a)
    a = re.sub(r"\s+", " ", a).strip()
    return a


def completeness(r: dict) -> tuple:
    raw = r.get("raw") or {}
    score = len(raw)
    for f in ("case_number", "opening_bid", "sale_date", "owner_name", "owner_phone"):
        if r.get(f):
            score += 1
    return (score, str(r.get("source") or ""))


def build_plan() -> tuple[list[list[str]], list[dict], int]:
    """Two bounded streaming passes over the live board -> (merge_groups, skipped, existing_total).
    merge_groups is already in merge_duplicate_rows()'s exact shape: kept hash first."""
    path = DOCS / "listings.json.gz"

    print("pass 1/2: streaming for identifiers + addresses only (bounded memory)...")
    light: dict[str, list[str]] = {}
    n = 0
    for rec in iter_board_rows(path):
        n += 1
        ident = identifier(rec)
        if ident:
            light.setdefault(ident, []).append(norm_addr(rec.get("street_address")))
    print(f"  scanned {n:,} rows, {len(light):,} distinct identifiers")

    candidates: set[str] = set()
    for ident, addrs in light.items():
        if len(addrs) < 2:
            continue
        distinct = {a for a in addrs if a}
        if len(distinct) >= FUSION_THRESHOLD:
            continue  # fused/placeholder identifier, same rule board_selfcheck.py uses
        candidates.add(ident)
    del light
    print(f"  candidate real-duplicate identifiers: {len(candidates):,}")

    print("pass 2/2: streaming again, retaining only candidate rows...")
    groups: dict[str, list[dict]] = {}
    n2 = 0
    for rec in iter_board_rows(path):
        n2 += 1
        ident = identifier(rec)
        if ident in candidates:
            groups.setdefault(ident, []).append(rec)
    if n2 != n:
        raise RuntimeError(f"board row count changed between passes ({n} vs {n2}) -- "
                            f"another writer touched it, aborting")
    print(f"  retained {sum(len(v) for v in groups.values()):,} rows "
          f"across {len(groups):,} groups")

    merge_groups: list[list[str]] = []
    skipped: list[dict] = []
    for key, g in groups.items():
        addrs_norm = [norm_addr(r.get("street_address")) for r in g]
        distinct = {a for a in addrs_norm if a}
        if len(distinct) != 1:
            reason = "zero_addresses" if not distinct else f"{len(distinct)}_distinct_streets"
            skipped.append({"key": key, "n": len(g), "reason": reason})
            continue
        the_addr = next(iter(distinct))
        carriers = sorted((r for r, a in zip(g, addrs_norm) if a == the_addr),
                          key=completeness, reverse=True)
        kept_row = carriers[0]
        other_rows = [r for r in g if r is not kept_row]
        kept_hash = row_identity_hash(kept_row)
        other_hashes = [row_identity_hash(r) for r in other_rows]
        all_hashes = [kept_hash] + other_hashes
        if len(set(all_hashes)) != len(all_hashes):
            skipped.append({"key": key, "n": len(g), "reason": "duplicate_identity_hash_in_group"})
            continue
        merge_groups.append(all_hashes)

    # --- cross-group collision guard ---
    # merge_duplicate_rows() itself refuses (before any I/O) if one identity key appears in two
    # DIFFERENT groups -- found for real on the first --execute attempt tonight (identity key
    # 'c32dcaa4...' in both group 252 and group 257). row_identity_hash() deliberately excludes
    # parcel_id (see its own docstring: parcel_id is a field the resolver revises post-publish),
    # so two rows that were grouped under two DIFFERENT parcel_id-based identifiers can still
    # collide on the narrow source/address/case/parties/sale hash if that content is otherwise
    # identical -- plausibly a genuine transitive duplicate (A~B via one parcel key, B~C via
    # another), but resolving that correctly needs the kind of manual judgment this script's own
    # rule already declines to automate. Simplest safe fix, consistent with "skip the ambiguous
    # ones": drop EVERY group that shares a key with another group, not just one side of the pair.
    key_count: dict[str, int] = {}
    for g in merge_groups:
        for k in g:
            key_count[k] = key_count.get(k, 0) + 1
    clean_groups = []
    collision_dropped = 0
    for g in merge_groups:
        if any(key_count[k] > 1 for k in g):
            collision_dropped += 1
            skipped.append({"key": "(cross-group collision)", "n": len(g),
                             "reason": "identity_key_shared_across_groups"})
            continue
        clean_groups.append(g)
    if collision_dropped:
        print(f"  cross-group identity-hash collisions: dropped {collision_dropped} group(s)")
    merge_groups = clean_groups

    # --- pass 3/3: full-board hash-uniqueness check ---
    # The first --execute attempt tonight was refused by merge_duplicate_rows() itself
    # (BoardMergeGroupMismatch, group 36) because one of our keys matched a row SOMEWHERE ELSE
    # on the board, outside our 2,583-row candidate subset -- a row_identity_hash() collision
    # against a row we never even looked at (row_identity_hash() deliberately excludes
    # parcel_id, so two structurally-unrelated rows -- different parcel/address identifier
    # groups entirely -- can still collide on the narrow source/address/case/parties/sale
    # subset). The cross-group check above only covers collisions AMONG our own candidate rows;
    # it cannot see this. So: hash the WHOLE board once more (strings only, ~20-30MB, cheap)
    # and drop any group touching a key that is not globally unique.
    print("pass 3/3: streaming the whole board once more for GLOBAL hash uniqueness...")
    global_counts: dict[str, int] = {}
    n3 = 0
    for rec in iter_board_rows(path):
        n3 += 1
        h = row_identity_hash(rec)
        global_counts[h] = global_counts.get(h, 0) + 1
    if n3 != n:
        raise RuntimeError(f"board row count changed during pass 3 ({n} vs {n3}) -- "
                            f"another writer touched it, aborting")
    final_groups = []
    global_collision_dropped = 0
    for g in merge_groups:
        if any(global_counts.get(k, 0) != 1 for k in g):
            global_collision_dropped += 1
            skipped.append({"key": "(global hash collision)", "n": len(g),
                             "reason": "identity_key_not_globally_unique"})
            continue
        final_groups.append(g)
    if global_collision_dropped:
        print(f"  global hash-uniqueness collisions: dropped {global_collision_dropped} group(s)")
    merge_groups = final_groups

    return merge_groups, skipped, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="audit + plan only, no lock, no writes")
    ap.add_argument("--execute", action="store_true", help="actually run merge_duplicate_rows()")
    args = ap.parse_args()
    if not args.dry_run and not args.execute:
        print("specify --dry-run or --execute", file=sys.stderr)
        return 2

    merge_groups, skipped, existing_total = build_plan()
    rows_targeted = sum(len(g) for g in merge_groups)
    rows_dropped = sum(len(g) - 1 for g in merge_groups)
    print(f"\n=== plan ===")
    print(f"existing board rows (this scan): {existing_total:,}")
    print(f"groups SAFE to merge: {len(merge_groups):,}  "
          f"(rows targeted: {rows_targeted:,}, rows to drop: {rows_dropped:,})")
    print(f"expected total_after: {existing_total - rows_dropped:,}")
    reason_counts: dict = {}
    for s in skipped:
        reason_counts[s["reason"]] = reason_counts.get(s["reason"], 0) + 1
    print(f"groups SKIPPED: {len(skipped):,}  {reason_counts}")

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    lock = board_lock(REPO, owner="dedupe_merge_20260930")
    with lock:
        stats = merge_duplicate_rows(
            merge_groups,
            {"dedupe_merge_20260930": f"{len(merge_groups)} groups, {rows_dropped} rows dropped, "
                                       f"real-duplicate cleanup per docs/HANDOFF.md follow-up "
                                       f"to commit 6719e6bd"},
            docs_dir=DOCS,
        )
    print("\n=== merge_duplicate_rows result ===")
    print(json.dumps(stats, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
