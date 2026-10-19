#!/usr/bin/env python3
"""One-off backfill: run the REAL, unmodified enrichment_tax_aging.enrich_tax_aging() over the
ALREADY-PUBLISHED board, for rows main.py's normal pipeline tail never got to apply it to.

WHY THIS EXISTS (gap-matrix sweep, 2026-10-19, tax_aging_surfaced sourced-not-built investigation)
    gap_matrix.py's fresh regen (464e4f8c, 447,004 rows) shows tax_aging_surfaced as
    "sourced-not-built" for 30 counties / 56,542 rows -- every one of those counties shows ZERO
    rows ever credited with a real (non-"default") raw['tax_aging_surfaced']. The Spec's own
    precondition is raw['tax_owed']['year'] or raw['nc_ptscloud_delinquent_tax']['tax_year']
    (see enrichment_tax_aging.py's docstring and SPECS["tax_aging_surfaced"] in gap_matrix.py).

    Live-sampled via board_stream (read-only, this investigation): of these 30 counties, 29 are a
    genuine upstream data gap -- zero rows carry ANY tax-ish raw key at all, or (Carteret, SC
    Beaufort, SC Marion) the only tax_owed block present is folded from a NON-property-tax source
    (national.zillow_foreclosures, counties_sc.sc_dew_lien_registry, counties_sc.sc_state_tax_lien,
    counties_generic.liensnc -- none of which ever states a levy year or a years-delinquent count).
    Nothing for enrich_tax_aging to surface there without a brand-new tax-roll reader per county
    (scoped, NOT attempted here -- see the investigation's own report, not this script).

    Brunswick NC is the one real exception: 3,776 of its 9,225 rows (41%) already carry a fully
    valid raw['tax_owed']['year'] (folded from counties_nc.nc_its_public_tax), yet ALL 3,776 show
    ZERO raw['tax_aging_surfaced'] of any kind, not even a stale "default" stamp. Directly unit-
    testing enrich_tax_aging() against one of these exact rows (this investigation, 2026-10-19)
    proves the function's own logic is correct and DOES compute tax_aging_surfaced for this exact
    shape -- so this is not a precondition bug and not an upstream data gap. It is the same
    "never actually applied to the full historical board" defect enrichment_tax_aging.py's own
    docstring already documented once (measured 2026-10-03: 41,083 rows/49 counties had the raw
    key but only 2,120 rows/11 counties were credited) and that enrichment_amount_owed's sibling
    backfill (scripts/backfill_tax_owed_amount_owed.py) fixed for a different field the same way.
    enrich_tax_aging() is wired into main.py's run_enrich_tail (main.py ~3586), which only ever
    runs over that run's OWN `enriched`/merged list in memory -- rows whose tax_owed landed on an
    earlier run and were not re-touched since (no resolver re-match, no dedupe collision, nothing)
    can sit with the precondition satisfied indefinitely without ever reaching this producer. This
    script closes that gap for the rows that already qualify, without touching
    enrichment_tax_aging.py itself.

    Idempotent and additive-only: NEVER overwrites an existing raw['tax_aging_surfaced'] (the
    live board shows none exist yet for these rows, but the guard costs nothing and matches
    enrich_tax_aging()'s own "a listing with neither source is left untouched" discipline for a
    one-off batch tool). No network. Fills only; never adds/removes/reorders a row, so the board's
    count guard is untouched.

BOARD I/O (same pattern as scripts/backfill_tax_owed_amount_owed.py)
    Streamed read-only via board_stream.iter_board_rows() -- never load_board() (this board's
    4.9 GB raw size is well past BOARD_LOAD_MAX_SOURCE_MB). enrich_tax_aging() itself only reads
    li.raw/li.state/li.county/li.source, so each row is wrapped in a cheap, unvalidated
    Listing.model_construct(...) rather than a real Listing.model_validate(...) -- no row pays for
    validation it doesn't need. Collision-guarded exactly like
    backfill_tax_owed_amount_owed.py: dedupe_key() is tallied in one pass across the WHOLE board
    (every row counts, eligible or not) and a key shared by more than one distinct row is dropped
    from the patch set entirely (reported as skipped_collision), never guessed at.

    python scripts/backfill_tax_aging_surfaced.py --dry-run
    python scripts/backfill_tax_aging_surfaced.py --dry-run --county Brunswick --state NC
    python scripts/backfill_tax_aging_surfaced.py          # applies (orchestrating session only)
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_tax_aging import enrich_tax_aging  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

#: Same identity fields patch_existing_rows()/append_new_rows() use internally
#: (web_artifact._APPEND_SIG_FIELDS) -- kept as a local literal, like
#: backfill_tax_owed_amount_owed.py does, rather than importing a private symbol.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")

CHECKPOINT_EVERY = 20_000  # rows scanned between patch_existing_rows() writes


def _dedupe_key(rec: dict) -> Optional[str]:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def _candidate(rec: dict) -> Optional[Listing]:
    """A cheap, unvalidated Listing wrapping this row's raw dict IN PLACE (no copy -- enrich_tax_aging
    mutates li.raw and we read the same dict back), or None for a row with no raw dict at all."""
    raw = rec.get("raw")
    if not isinstance(raw, dict):
        return None
    return Listing.model_construct(
        state=rec.get("state"), county=rec.get("county"), source=rec.get("source"),
        listing_type=rec.get("listing_type"), parcel_id=rec.get("parcel_id"), raw=raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="Stop after inspecting this many board rows (testing)")
    ap.add_argument("--state", default=None, help="Restrict to one state (e.g. NC)")
    ap.add_argument("--county", default=None, help="Restrict to one county (e.g. Brunswick)")
    args = ap.parse_args()

    docs = REPO / "docs"
    want_state = (args.state or "").strip().upper() or None
    want_county = (args.county or "").strip() or None
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="backfill_tax_aging_surfaced")

    with lock:
        key_counts: Counter = Counter()
        patches: dict[str, dict] = {}
        patch_source: dict[str, str] = {}
        by_source_stats: Counter = Counter()
        scanned = 0
        in_scope_rows = 0
        already_had_it = 0
        skipped_no_key = 0

        for rec in iter_board_rows(docs / "listings.json.gz"):
            scanned += 1
            key = _dedupe_key(rec)
            if key is None:
                skipped_no_key += 1
            else:
                key_counts[key] += 1

            st = (rec.get("state") or "").strip().upper()
            co = (rec.get("county") or "").strip()
            if want_state and st != want_state:
                pass
            elif want_county and co != want_county:
                pass
            else:
                in_scope_rows += 1
                raw = rec.get("raw") or {}
                existing_ta = raw.get("tax_aging_surfaced")
                if isinstance(existing_ta, dict) and existing_ta:
                    already_had_it += 1
                elif key is not None:
                    li = _candidate(rec)
                    if li is not None:
                        enrich_tax_aging([li])
                        new_ta = li.raw.get("tax_aging_surfaced")
                        if isinstance(new_ta, dict) and new_ta:
                            patches[key] = {"raw": {"tax_aging_surfaced": new_ta,
                                                     "tax_aging_high": li.raw.get("tax_aging_high")}}
                            patch_source[key] = rec.get("source") or "?"
                            by_source_stats[(st, co)] += 1
            if args.limit and scanned >= args.limit:
                break

        collision_keys = {k for k in patches if key_counts[k] > 1}
        for k in collision_keys:
            del patches[k]
            by_source_stats_key = patch_source.pop(k, None)

        print(f"scanned {scanned:,} board rows | in-scope "
              f"({want_state or 'any'}/{want_county or 'any'}): {in_scope_rows:,} | "
              f"already carried tax_aging_surfaced: {already_had_it:,}")
        print(f"newly eligible (precondition satisfied, enrich_tax_aging() computed a real "
              f"status): {len(patches) + len(collision_keys):,}")
        print(f"  of those, dropped as dedupe_key collisions: {len(collision_keys):,} "
              f"(no dedupe key at all: {skipped_no_key:,})")
        print(f"  landable this run: {len(patches):,}")
        print("by (state, county):")
        for (st, co), n in by_source_stats.most_common(30):
            print(f"  {n:7,d}  {st}/{co}")

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
            return 0

        items = list(patches.items())
        applied_total = 0
        for i in range(0, len(items), CHECKPOINT_EVERY):
            chunk = dict(items[i:i + CHECKPOINT_EVERY])
            stats = patch_existing_rows(
                chunk, {"backfill_tax_aging_surfaced": f"chunk={i}"}, docs_dir=docs)
            applied_total += stats["applied"]
            print(f"  [checkpoint {i}] patched {stats['applied']}/{len(chunk)} "
                  f"(existing board: {stats['existing']:,}, "
                  f"not_found: {stats['not_found']}, "
                  f"duplicate_key_matches: {stats['duplicate_key_matches']})", flush=True)

        print(f"\n=== RESULTS ===")
        print(f"rows scanned: {scanned:,}")
        print(f"rows patched: {applied_total:,}")
        print(f"dropped as dedupe_key collisions: {len(collision_keys):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
