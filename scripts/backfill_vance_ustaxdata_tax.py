#!/usr/bin/env python3
"""One-time backfill: run the already-shipped ustaxdata.com DIRECT-PARCEL chain
(enrichment_ustaxdata_tax_search.enrich_ustaxdata -> enrichment_tax_owed.enrich_tax_owed ->
enrichment_tax_aging.enrich_tax_aging) over Vance NC's already-published board rows, now that
Vance is a wired TENANTS entry (2026-11-17, round 17's 93-cell "no source known" tax-column
sweep).

WHY THIS EXISTS (same shape as scripts/backfill_rockingham_ustaxdata_tax.py, 2026-10-20, which
this file is adapted from almost line for line). vance.ustaxdata.com is live-verified real:
the board's own parcel_id, "0210 06002" (WITH its inner space, unmodified), passed straight to
this vendor's parcelNum field returns 18 real bill-year records / account 15907 (owner MSDG
HENDERSON LLC) -- cross-checked by an independent businessName search on the same form (same
18 records/account) and a second, unrelated real board row (lastName=BELL&firstName=GAVIN, 2
more real records/account 1039115). Unlike Rockingham/Alexander, Vance did NOT need
NAME_SEARCH_TENANTS -- it is wired in TENANTS (direct parcelNum), the same shape as Robeson, so
enrich_ustaxdata's own eligibility (`li.parcel_id and search_url(li.county, li.parcel_id)`) is
the gate here, not owner_name/street_address (Rockingham/Alexander's own NAME_SEARCH_TENANTS
precondition) -- this is this script's one real difference from the Rockingham template.

Like the Rockingham chain, this one is NOT flag-gated off (FORECLOSURE_USTAXDATA defaults to
"1") but is simply never run against an EXISTING already-published row, because the standard
pipeline enriches newly scraped rows each cycle, not the whole historical board -- so a backfill,
not a wait for normal cadence, is what actually lands this on Vance's existing rows.

NOT SCOPED HERE, same as Rockingham's own backfill and for the same confirmed reason
(enrichment_ustaxdata_tax_search.py's own docstring): nothing in this chain ever writes
raw['two_year_delinquent'] or raw['multi_year_delinquent_tax'] directly -- only
raw['ustaxdata_delinquent_tax'], raw['tax_owed'], and through it raw['tax_aging_surfaced'].
enrichment_ustaxdata_multiyear_tax.py is the SEPARATE, pure-compute restatement that reads
raw['ustaxdata_delinquent_tax'] a second way to actually write multi_year_delinquent_tax/
two_year_delinquent -- this script lands the data those keys read FROM, but does not itself
call that restatement (a later, cheap, idempotent pass can re-run it over the whole board, same
as every other restatement module in this project).

BOARD I/O: streams docs/ once via web_artifact._iter_board_records() (never json.load(), never
load_board()/write_artifact()) and lands the result set with ONE patch_existing_rows() call
under board_lock(), same discipline as every backfill before this one.

Usage:
    python scripts/backfill_vance_ustaxdata_tax.py --dry-run
    python scripts/backfill_vance_ustaxdata_tax.py --dry-run --max-batches 1
    python scripts/backfill_vance_ustaxdata_tax.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.enrichment_tax_aging import enrich_tax_aging  # noqa: E402
from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed  # noqa: E402
from foreclosure_scraper.enrichment_ustaxdata_tax_search import enrich_ustaxdata  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, _iter_board_records, board_lock, board_patch_size_state,
    patch_existing_rows,
)

COUNTY = "Vance"
_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name", "tax_value")
_WATCH_KEYS = ("ustaxdata_delinquent_tax", "tax_owed", "tax_aging_surfaced", "tax_aging_high",
              "tax_not_yet_late", "tax_big_old")


def _is_vance_nc(rec: dict) -> bool:
    return (str(rec.get("county") or "").replace(" County", "").strip().lower() == COUNTY.lower()
            and str(rec.get("state") or "").upper() == "NC")


def _already_done(raw) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get("ustaxdata_delinquent_tax"), dict)


def _light(rec: dict) -> Listing:
    li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS if k in rec})
    if not isinstance(li.raw, dict):
        li.raw = {}
    return li


def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], int, int]:
    """{dedupe_key: light_listing} for every Vance NC row with a parcel_id (enrich_ustaxdata's
    OWN direct-parcel eligibility: `li.parcel_id and search_url(li.county, li.parcel_id)` --
    NOT owner_name/street_address, which is only the NAME_SEARCH_TENANTS precondition Rockingham/
    Alexander need) that isn't already carrying raw['ustaxdata_delinquent_tax']. Streamed via
    _iter_board_records -- never json.load(), never the whole board held as a parsed list."""
    cands: dict[str, Listing] = {}
    seen: dict[str, int] = {}
    total = 0
    for rec in _iter_board_records(docs):
        total += 1
        if not _is_vance_nc(rec):
            continue
        if not rec.get("parcel_id"):
            continue
        if _already_done(rec.get("raw")):
            continue
        li = _light(rec)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        seen[key] = seen.get(key, 0) + 1
        cands[key] = li
    ambiguous = 0
    for key, n in seen.items():
        if n > 1:
            cands.pop(key, None)
            ambiguous += 1
    return cands, total, ambiguous


async def _run_one_batch(listings: list[Listing]) -> dict:
    """One pass of the real, unmodified pipeline chain, in order (main.py's own order:
    ustaxdata -> tax_owed -> tax_aging)."""
    ustx_stats = await enrich_ustaxdata(listings)
    owed_stats = enrich_tax_owed(listings)
    aging_stats = enrich_tax_aging(listings)
    return {"ustaxdata": ustx_stats, "tax_owed": owed_stats, "tax_aging": aging_stats}


def _build_patches(candidates: dict[str, Listing], before: dict[str, dict]) -> dict[str, dict]:
    patches: dict[str, dict] = {}
    for key, li in candidates.items():
        after_raw = li.raw if isinstance(li.raw, dict) else {}
        b_raw, b_tax_value = before[key]
        raw_patch = {k: after_raw.get(k) for k in _WATCH_KEYS if after_raw.get(k) != b_raw.get(k)}
        patch: dict = {}
        if raw_patch:
            patch["raw"] = raw_patch
        if li.tax_value is not None and li.tax_value != b_tax_value:
            patch["tax_value"] = li.tax_value
        if patch:
            patches[key] = patch
    return patches


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--max-batches", type=int, default=10,
                    help="Batches of up to USTAXDATA_MAX_PARCELS (default 300) rows this "
                         "invocation will run. Default 10 (up to 3,000 attempts).")
    args = ap.parse_args()

    docs = REPO / "docs"

    import contextlib
    import os
    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="vance_ustaxdata_backfill")
    with lock:
        candidates, total_rows, ambiguous = _collect_candidates(docs)
        print(f"board rows streamed: {total_rows:,}")
        print(f"{COUNTY} NC eligible candidates (has parcel_id, not yet checked): "
              f"{len(candidates):,}")
        if ambiguous:
            print(f"excluded as ambiguous-identity (shared dedupe_key with another candidate, "
                  f"never guessed at): {ambiguous:,}")

        before = {key: (dict(li.raw) if isinstance(li.raw, dict) else {}, li.tax_value)
                 for key, li in candidates.items()}

        listings = list(candidates.values())
        batch_stats = []
        if listings:
            print(f"\n=== {COUNTY} NC: running the real ustaxdata -> tax_owed -> tax_aging "
                  f"chain in batches ===")
            for i in range(args.max_batches):
                remaining = sum(1 for li in listings if not _already_done(li.raw))
                if remaining == 0:
                    print(f"batch {i + 1}: nothing left eligible, stopping early")
                    break
                stats = asyncio.run(_run_one_batch(listings))
                stats["batch"] = i + 1
                stats["remaining_before_batch"] = remaining
                print(f"  batch {i + 1}: {stats}")
                batch_stats.append(stats)
                if stats["ustaxdata"].get("fetched", 0) == 0 and stats["ustaxdata"].get("eligible", 0) == 0:
                    break  # nothing left this module considers eligible

        patches = _build_patches(candidates, before)
        print(f"\npatches staged: {len(patches):,}")
        confirmed = sum(1 for p in patches.values()
                        if isinstance(p.get("raw", {}).get("ustaxdata_delinquent_tax"), dict)
                        and p["raw"]["ustaxdata_delinquent_tax"].get("status") not in
                        ("no_record", "name_search_unconfirmed"))
        print(f"    confirmed real bill history: {confirmed:,}")
        print(f"    checked, no usable answer (no_record/unconfirmed/no match): "
              f"{len(patches) - confirmed:,}")

        if args.dry_run:
            print("\nDRY RUN -- nothing written. (Note: enrich_ustaxdata above still hits the "
                  "real live vendor -- this module has no network-free dry-run mode; --dry-run "
                  "here only controls whether the result is WRITTEN to the board.)")
            return 0
        if not patches:
            print("\nnothing to do.")
            return 0

        size_state = board_patch_size_state(docs)
        if not size_state["ok"] and not args.allow_large:
            print(f"\nREFUSING: {size_state['reason']}. Re-run with --allow-large under "
                  f"supervision.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

        stats_patch = patch_existing_rows(
            patches, {"vance_ustaxdata_backfill": len(patches), "ambiguous": ambiguous},
            docs_dir=docs)
        print(f"\nwrote board: patched {stats_patch['applied']:,}/{len(patches):,} rows "
              f"(existing board: {stats_patch['existing']:,}, not_found: "
              f"{stats_patch['not_found']:,}, duplicate_key_matches: "
              f"{stats_patch['duplicate_key_matches']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
