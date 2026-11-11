#!/usr/bin/env python3
"""Run enrichment_tax_owed over the published board to recover delinquent-tax YEAR.

Why this exists: tax delinquency is the primary lead filter for this business,
and the operative cut is "2-3 years behind" - one year is too early, the owner
still believes they will catch up. On the published board only 2.6% of the
90,414 tax-delinquent leads carry a usable year, so that filter can be applied
to almost nothing.

The three bugs that caused it (RAW_KEEP stripping source sub-dicts, the generic
scan self-matching raw['tax_owed'] from a prior run, and _SOURCES covering only
3 sources) were all FIXED in code on 2026-08-24 but only committed in the
2026-08-30 WIP snapshot - after the last successful board build on 2026-08-27.
So the fix has never actually run against the board. This runs it.

enrich_tax_owed is pure offline (no network). Fills only; never adds or removes
a row, so the count guard is untouched.

REWRITTEN TWICE 2026-11-10 (gap-sweep wave 2, tax_aging_surfaced investigation).

Attempt 1 called load_board() unconditionally, which at this board's size
(474k+ rows / 5.1GB+ raw, climbing) risks the memory exhaustion this project
has already hit multiple times (feedback_load_board_scale_blowup memory).

Attempt 2 tried the backfill_multiyear_tax_restatement.py trick -- stream the
whole board once into ONE Python list of cheap Listing.model_construct()s,
reasoning that skipping full Pydantic validation would make holding all 474k
rows affordable. Measured live on the VM (24GB RAM): peak RSS climbed past
13GB, then past 18GB on a second, "optimized" attempt that only trimmed one
of several per-row copies -- and briefly pushed the whole VM to 19GB used /
4.7GB of 5GB swap consumed, a genuine near-OOM caught and killed live. The
flaw in the reasoning: enrich_tax_owed() needs the WHOLE board in memory
together only because its own cross-reference pass (pass 2) looks up other
rows by key -- and holding 474k rows' raw dicts (which is where the real size
lives, not Listing's own ~60 other fields) was never actually cheap just
because Listing.model_validate() was skipped.

THE ACTUAL FIX: enrich_tax_owed()'s cross-reference index
(enrichment_tax_owed._county_county_key()) is keyed by (state, county,
parcel) -- a cross-reference can NEVER match across two different counties.
So the whole-board dependency is false: processing ONE (state, county) at a
time through enrich_tax_owed() gives IDENTICAL cross-reference results to
processing the whole board at once, while bounding peak memory to the
largest single county's row count (a small fraction of 474k) instead of the
whole board.

Two-pass design:
  Pass A streams the board ONCE (iter_board_rows(), never load_board()) and
  writes each row needing inspection into one per-(state,county) JSONL temp
  file on disk (only the LIGHT fields enrich_tax_owed()/the stats helpers
  read -- raw/source/parcel_id/state/county/listing_type/the dedupe-key
  fields -- never the whole row). This bounds Pass A's own memory to one
  row at a time, trading disk for RAM (the VM has 135GB+ free; memory was
  the scarce resource, confirmed live).
  Pass B processes each county's temp file independently: load just that
  county's light Listings, run the REAL enrich_tax_owed() unmodified (same
  "don't re-derive the production function" discipline backfill_tax_aging_
  surfaced.py already established), diff before/after 'tax_owed', stage
  patches keyed by dedupe_key with the SAME collision guard as before (now
  computed per-county, which is equivalent to global since dedupe_key()
  includes county -- two rows in different counties can never collide).
  Patches accumulate in one dict across all counties (patches are tiny --
  one dedupe_key + one tax_owed sub-dict -- nothing like holding full rows)
  and are written at the end via patch_existing_rows() in CHECKPOINT_EVERY
  chunks, same as before.

HONEST CAVEAT: enrich_tax_owed()'s own Pass 0 (tax_binding.scrub_unbound_tax,
a protective step that strips a tax block when it looks shared/copied across
MANY different properties -- see MASS_COPY_PROPERTIES) runs over whatever
`listings` it's given. Scoping that to one county at a time means a
mass-copy artifact that happened to span MULTIPLE counties (not verified
either way -- the one calibration example in that module's own comments,
Lincoln, is single-county) would be scrubbed less aggressively than a true
whole-board pass. This is a fail-OPEN risk (slightly less scrubbing of a
rare cross-county edge case), not a fail-CLOSED one (no new bad data gets
introduced) -- an accepted, explicitly logged tradeoff against the
alternative (an 18GB+ single-process peak that already forced an emergency
kill once) rather than a silent one.

    python scripts/backfill_tax_aging.py --dry-run
    python scripts/backfill_tax_aging.py
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
DOCS = REPO / "docs"
NOW_YEAR = 2026

_YEARISH = ("year", "tax_year", "first_cycle", "latest_cycle", "bill_year",
            "oldest_year", "bill_years", "tax_years", "year_span")

#: fields enrich_tax_owed() and _stats()/_year_of()/dedupe_key() read -- same idea as
#: backfill_multiyear_tax_restatement.py's _LIGHT_FIELDS / _APPEND_SIG_FIELDS.
_LIGHT_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                  "case_number", "source_url", "listing_type", "source", "raw")

CHECKPOINT_EVERY = 20_000  # rows between patch_existing_rows() writes


def _year_of(li) -> int | None:
    raw = li.raw if isinstance(getattr(li, "raw", None), dict) else {}
    to = raw.get("tax_owed") or {}
    if not isinstance(to, dict):
        return None
    for k in _YEARISH:
        v = to.get(k)
        if isinstance(v, int) and 1990 < v <= NOW_YEAR:
            return v
        if isinstance(v, str):
            m = re.search(r"(19|20)\d{2}", v)
            if m:
                y = int(m.group(0))
                if 1990 < y <= NOW_YEAR:
                    return y
        if isinstance(v, list) and v:
            ys = [int(re.search(r"(19|20)\d{2}", str(x)).group(0))
                  for x in v if re.search(r"(19|20)\d{2}", str(x))]
            ys = [y for y in ys if 1990 < y <= NOW_YEAR]
            if ys:
                return min(ys)
    return None


def _stats_update(s, li) -> None:
    raw = li.raw if isinstance(getattr(li, "raw", None), dict) else {}
    lt = str(getattr(li, "listing_type", "") or "").lower()
    if not ("tax" in lt or raw.get("tax_owed") or raw.get("two_year_delinquent")):
        return
    s["tax"] += 1
    y = _year_of(li)
    if y:
        s["with_year"] += 1
    to = raw.get("tax_owed") or {}
    if isinstance(to, dict) and (to.get("amount") or to.get("balance")):
        s["with_amount"] += 1


def _foot_stats_update(s, li, in_scope, y) -> None:
    if not y:
        return
    foot = bool(getattr(li, "county", None)) and in_scope(li.county, li.state)
    if not foot:
        return
    age = NOW_YEAR - y
    if age >= 2:
        s["foot_2yr"] += 1
    if age >= 3:
        s["foot_3yr"] += 1


def _county_key(rec: dict) -> tuple[str, str]:
    return ((rec.get("state") or "").strip().upper() or "??",
            (rec.get("county") or "").strip() or "??")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from foreclosure_scraper.board_stream import iter_board_rows
    from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed
    from foreclosure_scraper.config import in_scope
    from foreclosure_scraper.models import Listing
    from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows

    # wait=3600/poll=10 matches backfill_gis_attrs_boardwide.py's own convention -- without an
    # explicit wait, board_lock()'s default (wait=0.0) raises BoardLockBusy immediately instead
    # of queuing behind a concurrently-running writer.
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="backfill_tax_aging", wait=3600, poll=10)

    with lock:
        with tempfile.TemporaryDirectory(prefix="backfill_tax_aging_") as tmpdir:
            tmp = Path(tmpdir)
            # Pass A: one streaming read, fan out into per-county JSONL files. Bounded memory:
            # at most a handful of open file handles' worth of OS buffering, never the whole board.
            handles: dict[tuple[str, str], "object"] = {}
            total_rows = 0
            counties_seen: set[tuple[str, str]] = set()
            # No upfront filter here: enrich_tax_owed()'s own _extract_via() scans ~20 different
            # named raw blocks (enrichment_tax_owed._SOURCES) for a balance, none of which require
            # listing_type to already say "tax" or raw['tax_owed']/raw['two_year_delinquent'] to
            # already exist (those are this function's OWN output) -- filtering here on that
            # narrower condition, as _stats()'s REPORTING-only filter does, would silently drop
            # real candidates the original whole-board call never missed. Every row goes to its
            # county file; the cost is disk, not memory, and disk is not the scarce resource here
            # (135GB+ free on this VM vs. the 18GB+ single-process RSS that forced an emergency
            # kill under the whole-board-in-RAM approach).
            try:
                for rec in iter_board_rows(DOCS / "listings.json.gz"):
                    total_rows += 1
                    raw = rec.get("raw")
                    if not isinstance(raw, dict):
                        continue
                    ck = _county_key(rec)
                    counties_seen.add(ck)
                    fh = handles.get(ck)
                    if fh is None:
                        fh = open(tmp / f"{ck[0]}__{ck[1]}.jsonl", "w")
                        handles[ck] = fh
                    fh.write(json.dumps({k: rec.get(k) for k in _LIGHT_FIELDS}) + "\n")
            finally:
                for fh in handles.values():
                    fh.close()

            print(f"board {total_rows:,} rows scanned | "
                  f"{sum(1 for _ in tmp.glob('*.jsonl')):,} counties carry a tax-ish row")

            # Pass B: one county at a time. enrich_tax_owed()'s own cross-reference index is
            # (state, county, parcel)-keyed, so this is lossless vs. a single whole-board pass.
            before = collections.Counter()
            after = collections.Counter()
            patches: dict[str, dict] = {}
            collisions = 0
            applied_total = 0
            items_buffer: list[tuple[str, dict]] = []

            def _flush(force: bool = False):
                nonlocal applied_total, items_buffer
                if args.dry_run:
                    items_buffer = []
                    return
                if len(items_buffer) >= CHECKPOINT_EVERY or (force and items_buffer):
                    chunk = dict(items_buffer)
                    stats = patch_existing_rows(
                        chunk, {"backfill_tax_aging": f"n={len(chunk)}"}, docs_dir=DOCS)
                    applied_total += stats["applied"]
                    print(f"  [checkpoint] patched {stats['applied']}/{len(chunk)} "
                          f"(existing board: {stats['existing']:,}, "
                          f"not_found: {stats['not_found']}, "
                          f"duplicate_key_matches: {stats['duplicate_key_matches']})", flush=True)
                    items_buffer = []

            for ck in sorted(counties_seen):
                path = tmp / f"{ck[0]}__{ck[1]}.jsonl"
                recs = [json.loads(line) for line in path.open()]
                board = []
                keys = []
                before_tax_owed = []
                for rec in recs:
                    li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
                    board.append(li)
                    try:
                        keys.append(li.dedupe_key())
                    except Exception:  # noqa: BLE001 - too malformed to key, simply unpatchable
                        keys.append(None)
                    to = li.raw.get("tax_owed") if isinstance(li.raw, dict) else None
                    before_tax_owed.append(dict(to) if isinstance(to, dict) else None)
                key_counts = collections.Counter(k for k in keys if k is not None)

                # BEFORE stats, including footprint -- must run before enrich_tax_owed() mutates
                # li.raw['tax_owed'] in place, since this is the only point li's own _year_of()
                # reflects the pre-enrichment value.
                for li in board:
                    _stats_update(before, li)
                    _foot_stats_update(before, li, in_scope, _year_of(li))

                enrich_tax_owed(board)

                for li in board:
                    _stats_update(after, li)
                    _foot_stats_update(after, li, in_scope, _year_of(li))

                if not args.dry_run:
                    for li, key, b4_to in zip(board, keys, before_tax_owed):
                        new_to = li.raw.get("tax_owed") if isinstance(li.raw, dict) else None
                        if not new_to or new_to == b4_to:
                            continue
                        if key is None:
                            continue
                        if key_counts[key] > 1:
                            collisions += 1
                            continue
                        patches[key] = {"raw": {"tax_owed": new_to}}
                        items_buffer.append((key, {"raw": {"tax_owed": new_to}}))
                    _flush()

            print(f"  BEFORE  year {before['with_year']:,} "
                  f"({before['with_year']/max(before['tax'],1)*100:.1f}%)  "
                  f"amount {before['with_amount']:,}  "
                  f"| in-footprint 2yr+ {before['foot_2yr']:,}  3yr+ {before['foot_3yr']:,}")
            print(f"  AFTER   year {after['with_year']:,} "
                  f"({after['with_year']/max(after['tax'],1)*100:.1f}%)  "
                  f"amount {after['with_amount']:,}  "
                  f"| in-footprint 2yr+ {after['foot_2yr']:,}  3yr+ {after['foot_3yr']:,}")
            print(f"\n  >>> year  +{after['with_year']-before['with_year']:,}")
            print(f"  >>> the operative filter (in-footprint, 2yr+): "
                  f"{before['foot_2yr']:,} -> {after['foot_2yr']:,}")

            if args.dry_run:
                print("\n--dry-run: nothing written")
                return 0

            _flush(force=True)
            print(f"\npatches staged: {len(patches):,} (dropped as dedupe_key collisions: "
                  f"{collisions:,}) | applied: {applied_total:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
