#!/usr/bin/env python3
"""One-time backfill: run the already-shipped ustaxdata.com name-search chain
(enrichment_ustaxdata_tax_search.enrich_ustaxdata -> enrichment_tax_owed.enrich_tax_owed ->
enrichment_tax_aging.enrich_tax_aging, commit ae2ca7df, 2026-10-16) over Rockingham NC's
already-published board rows.

WHY THIS EXISTS (2026-10-20 Rockingham gap-list ask). The 2026-10-20 gap list showed Rockingham
NC "sourced-not-built" for two_year_delinquent/tax_aging_surfaced/multi_year_delinquent_tax
against www.ustaxdata.com -- but the module that reaches this vendor for Rockingham (owner-name +
address-confirmed search, NAME_SEARCH_TENANTS) was already built and shipped 4 days earlier. Live
re-verification the same night confirmed the MECHANISM works end-to-end right now: a real
enrich_ustaxdata() call against live Rockingham board rows (owners "KNOWLES CAROL FAYE...",
"OAKES LEA ANN") returned real, address-confirmed, multi-year (2019-2026) bill histories with a
real 2026 unpaid year on both. scripts/gap_matrix.py's own built_in_code() was just fixed (same
session) to credit Rockingham/Alexander/Robeson for tax_aging_surfaced from this chain -- a pure
classification fix, same shape as the Mecklenburg/Carteret marriage_license fix.

But unlike that marriage_license fix (genuinely 0 rows today, by a deliberate env-flag cost hold),
THIS chain is NOT flag-gated off (FORECLOSURE_USTAXDATA defaults to "1", on) -- it is simply never
run against an EXISTING already-published row, because the standard pipeline enriches newly
scraped rows each cycle, not the whole historical board. Confirmed live: every sampled Rockingham
board row carries no raw['ustaxdata_delinquent_tax'] at all. So, unlike Mecklenburg, a backfill
here lands REAL rows (same shape as backfill_iredell_multiyear_tax.py / backfill_cabarrus_
multiyear_tax.py) -- this script is that backfill, scoped to Rockingham only.

NOT SCOPED HERE: two_year_delinquent and multi_year_delinquent_tax. Checked and confirmed (see
enrichment_ustaxdata_tax_search.py's corrected docstring, 2026-10-20): NOTHING in this chain ever
writes either column's own literal raw key (raw['two_year_delinquent'], raw[
'multi_year_delinquent_tax']) -- only raw['ustaxdata_delinquent_tax'], raw['tax_owed'] and, through
it, raw['tax_aging_surfaced']. This backfill will not move those two columns, and that is correct,
not a bug: they are a real, separate gap-list misattribution against this vendor (the same
vendor-attribution-imprecision pattern already documented for rollback_exposure here).

BOARD I/O: streams docs/ once via web_artifact._iter_board_records() (never json.load(), never
load_board()/write_artifact() -- those thrashed for 2+ hours on the VM without finishing earlier
tonight) and lands the small result set with ONE patch_existing_rows() call under board_lock(),
same discipline as every backfill before this one.

Usage:
    python scripts/backfill_rockingham_ustaxdata_tax.py --dry-run
    python scripts/backfill_rockingham_ustaxdata_tax.py --dry-run --max-batches 1
    python scripts/backfill_rockingham_ustaxdata_tax.py --allow-large
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

COUNTY = "Rockingham"
_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name", "tax_value")
#: everything this chain can touch on a row, watched for the before/after diff. tax_owed/
#: tax_aging_surfaced/tax_aging_high are the derived outputs real readers consume (fullmer_rank,
#: enrichment_equity); tax_not_yet_late/tax_big_old are the two dashboard-filter flags
#: enrich_tax_aging also (re)computes every run alongside them.
_WATCH_KEYS = ("ustaxdata_delinquent_tax", "tax_owed", "tax_aging_surfaced", "tax_aging_high",
              "tax_not_yet_late", "tax_big_old")


def _is_rockingham_nc(rec: dict) -> bool:
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
    """{dedupe_key: light_listing} for every Rockingham NC row with an owner_name AND
    street_address (enrich_ustaxdata's own _name_search_eligible precondition) that isn't already
    carrying raw['ustaxdata_delinquent_tax']. Streamed via _iter_board_records -- never
    json.load(), never the whole board held as a parsed list."""
    cands: dict[str, Listing] = {}
    seen: dict[str, int] = {}
    total = 0
    for rec in _iter_board_records(docs):
        total += 1
        if not _is_rockingham_nc(rec):
            continue
        if not (rec.get("owner_name") and rec.get("street_address")):
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
    ustaxdata -> tax_owed -> tax_aging). enrich_ustaxdata's own MAX_PARCELS cap (default 300)
    bounds how many NOT-already-done listings it touches per call, so repeated batches advance
    through the candidate set; enrich_tax_owed/enrich_tax_aging are cheap, pure, in-memory, and
    idempotent, so re-running them over the whole set every batch is harmless and keeps every
    row's derived fields current."""
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
                         "invocation will run. Default 10 (up to 3,000 attempts) comfortably "
                         "covers Rockingham's 2,241-row applicable set.")
    args = ap.parse_args()

    docs = REPO / "docs"

    import contextlib
    import os
    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="rockingham_ustaxdata_backfill")
    with lock:
        candidates, total_rows, ambiguous = _collect_candidates(docs)
        print(f"board rows streamed: {total_rows:,}")
        print(f"{COUNTY} NC eligible candidates (owner_name + street_address, not yet checked): "
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
            patches, {"rockingham_ustaxdata_backfill": len(patches), "ambiguous": ambiguous},
            docs_dir=docs)
        print(f"\nwrote board: patched {stats_patch['applied']:,}/{len(patches):,} rows "
              f"(existing board: {stats_patch['existing']:,}, not_found: "
              f"{stats_patch['not_found']:,}, duplicate_key_matches: "
              f"{stats_patch['duplicate_key_matches']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
