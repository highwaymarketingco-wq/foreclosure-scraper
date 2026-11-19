#!/usr/bin/env python3
"""One-time backfill: run the already-shipped ustaxdata.com chain
(enrichment_ustaxdata_tax_search.enrich_ustaxdata -> enrichment_ustaxdata_multiyear_tax.
enrich_ustaxdata_multiyear_tax -> enrichment_tax_owed.enrich_tax_owed ->
enrichment_tax_aging.enrich_tax_aging, main.py's own order) over Robeson and Alexander NC's
already-published board rows. Same shape as backfill_rockingham_ustaxdata_tax.py (2026-10-20) /
backfill_vance_ustaxdata_tax.py, just never done for these two tenants.

WHY THIS EXISTS (round 48 gap-matrix, 2026-11-18, after tonight's vacant_lot vein closed out).
docs/gap_matrix's sourced-not-built list still shows NC Robeson/Alexander "sourced-not-built"
for multi_year_delinquent_tax/two_year_delinquent against www.ustaxdata.com (Robeson alone:
1,653 applicable, the single largest sourced-not-built cell on tonight's board). Live board
read (board_stream, read-only, no county literal grep, no gap_matrix.py edited) confirms the
real reason, not the vendor-attribution-imprecision this project already correctly diagnosed
and left alone for rollback_exposure (commit ab9d5067) and for the sourced-not-built
MISATTRIBUTION gap_matrix.py's own built_in_code() already fixed for tax_aging_surfaced: this
chain is NOT flag-gated off (FORECLOSURE_USTAXDATA defaults to "1") and IS wired in main.py
every regular cycle -- it has simply NEVER been run against Robeson or Alexander's EXISTING
board rows, the exact same "enriches only newly-scraped rows, not the historical board" shape
backfill_rockingham_ustaxdata_tax.py's own docstring already diagnosed and fixed for Rockingham
four weeks ago, and backfill_vance_ustaxdata_tax.py fixed for Vance. Confirmed live by reading
raw['ustaxdata_delinquent_tax'] across every Robeson/Alexander/Rockingham/Vance NC board row
(read-only sweep, this session): Robeson 0/1,653 and Alexander 0/355 carry that key at all,
vs. Rockingham 1,144/2,289 and Vance 66/896 -- the two counties that already got a dedicated
backfill script. Robeson is the SIMPLEST tenant here (TENANTS: direct parcel_id -> account
match, no name-search ambiguity at all, confirmed live 2026-10-16 against a real board parcel);
Alexander is NAME_SEARCH_TENANTS (owner name + address-confirmed, same mechanism Rockingham's
own backfill already proved out at scale).

ALEXANDER'S DETAIL HOP IS A DOCUMENTED LIVE DEAD END (enrichment_ustaxdata_tax_search.py's own
2026-10-20 correction: every taxbill.cfm fetch there returns a vendor-side "Connection Timeout"
error page, not a bill) -- but that only costs `balance`/`total_due` on confirmed-unpaid bills,
never the per-year `status` icon the search/summary page itself already carries (bill_open.gif/
bill_partial.gif/bill_paid.gif, read by parse_results(), never by the broken detail hop). The
two target columns here are STATUS-based, not amount-based (enrichment_ustaxdata_multiyear_tax.
py's own docstring: "delinquency here is read from status in {unpaid, partial}... present on
every tenant regardless of whether the second-hop dollar-amount fetch succeeded") -- so
Alexander's live dead end does not block multi_year_delinquent_tax/two_year_delinquent, only
the balance dollar figure folded into tax_owed, same as it already does not block Rockingham's
own 217 real two_year_delinquent rows despite 927/1,144 Rockingham bills also failing to
resolve a balance.

INCLUDES THE MULTIYEAR RESTATEMENT STEP THE ROCKINGHAM SCRIPT'S BATCH LOOP DID NOT CALL.
backfill_rockingham_ustaxdata_tax.py predates enrichment_ustaxdata_multiyear_tax.py by 8 days
(2026-10-20 vs. 2026-10-28) and its own docstring correctly says, AS OF THAT DATE, nothing in
the chain wrote multi_year_delinquent_tax/two_year_delinquent. Live board read THIS session
shows Rockingham's own two_year_delinquent (217) and multi_year_delinquent_tax (24) now match
its udt_real_bills (217) / years_unpaid>=2 (24) counts EXACTLY -- the restatement module is
reaching Rockingham's already-patched rows via the regular nightly pipeline cycle (main.py
calls it on every `enriched` listing carrying the raw key, not gated on "newly scraped"), not
via that backfill script. Rather than assume a future nightly cycle will do the same for
Robeson/Alexander, this script calls enrich_ustaxdata_multiyear_tax() directly in the same
batch, so the two actually-targeted columns are verifiable THIS round, not deferred.

NOT SCOPED HERE: rollback_exposure. Already checked and correctly declined for Robeson/Alexander
(commit ab9d5067, 2026-11-16): this vendor's "Asset Description" cell is a static placeholder
on every row, every county tried -- no present-use/land-use field exists to read. Re-confirmed
by this script's own batch stats (block never carries a land-use/description field); not
revisited here.

BOARD I/O: streams docs/ once via web_artifact._iter_board_records() (never json.load(), never
load_board()/write_artifact()) and lands the result with ONE patch_existing_rows() call under
board_lock(), same discipline as every backfill before this one.

Usage:
    python scripts/backfill_robeson_alexander_ustaxdata_tax.py --dry-run
    python scripts/backfill_robeson_alexander_ustaxdata_tax.py --dry-run --max-batches 1
    python scripts/backfill_robeson_alexander_ustaxdata_tax.py --allow-large
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
from foreclosure_scraper.enrichment_ustaxdata_multiyear_tax import (  # noqa: E402
    enrich_ustaxdata_multiyear_tax,
)
from foreclosure_scraper.enrichment_ustaxdata_tax_search import (  # noqa: E402
    _name_search_eligible, enrich_ustaxdata, search_url,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, _iter_board_records, board_lock, board_patch_size_state,
    patch_existing_rows,
)

COUNTIES = {"robeson", "alexander"}
_LIGHT_FIELDS = _APPEND_SIG_FIELDS + ("raw", "owner_name", "tax_value")
#: everything this chain can touch on a row, watched for the before/after diff. Same set
#: backfill_rockingham_ustaxdata_tax.py watches, plus the two restated columns this script
#: additionally closes.
_WATCH_KEYS = ("ustaxdata_delinquent_tax", "multi_year_delinquent_tax", "two_year_delinquent",
              "tax_owed", "tax_aging_surfaced", "tax_aging_high", "tax_not_yet_late",
              "tax_big_old")


def _is_target_nc(rec: dict) -> bool:
    county = str(rec.get("county") or "").replace(" County", "").strip().lower()
    return county in COUNTIES and str(rec.get("state") or "").upper() == "NC"


def _already_done(raw) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get("ustaxdata_delinquent_tax"), dict)


def _light(rec: dict) -> Listing:
    li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS if k in rec})
    if not isinstance(li.raw, dict):
        li.raw = {}
    return li


def _eligible(li: Listing) -> bool:
    """Mirrors enrich_ustaxdata's own targets filter exactly (parcel_id path for Robeson,
    name-search path for Alexander) so this script's candidate count never drifts from what
    the real function will actually attempt."""
    return bool((li.parcel_id and search_url(li.county, li.parcel_id)) or _name_search_eligible(li))


def _collect_candidates(docs: Path) -> tuple[dict[str, Listing], int, int]:
    """{dedupe_key: light_listing} for every Robeson/Alexander NC row enrich_ustaxdata would
    actually attempt (parcel_id-resolvable for Robeson, owner_name+street_address for Alexander)
    that isn't already carrying raw['ustaxdata_delinquent_tax']. Streamed via
    _iter_board_records -- never json.load(), never the whole board held as a parsed list."""
    cands: dict[str, Listing] = {}
    seen: dict[str, int] = {}
    total = 0
    for rec in _iter_board_records(docs):
        total += 1
        if not _is_target_nc(rec):
            continue
        if _already_done(rec.get("raw")):
            continue
        li = _light(rec)
        if not _eligible(li):
            continue
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
    """One pass of the real, unmodified pipeline chain, main.py's own order: ustaxdata ->
    ustaxdata_multiyear_tax (restatement, no network) -> tax_owed -> tax_aging. enrich_ustaxdata's
    own MAX_PARCELS cap (default 300, shared across ALL its tenants -- Robeson+Alexander+
    Rockingham+Vance) bounds how many not-already-done listings it touches per call; since this
    script's `listings` is scoped to Robeson/Alexander only, the full 300 goes to this candidate
    set each batch. The other three steps are cheap, pure, in-memory and idempotent, so
    re-running them over the whole set every batch is harmless."""
    ustx_stats = await enrich_ustaxdata(listings)
    myr_stats = enrich_ustaxdata_multiyear_tax(listings)
    owed_stats = enrich_tax_owed(listings)
    aging_stats = enrich_tax_aging(listings)
    return {"ustaxdata": ustx_stats, "ustaxdata_multiyear": myr_stats,
            "tax_owed": owed_stats, "tax_aging": aging_stats}


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
                    help="Batches of up to USTAXDATA_MAX_PARCELS (default 300, shared across "
                         "this script's whole Robeson+Alexander candidate set). Default 10 "
                         "(up to 3,000 attempts) comfortably covers both counties' combined "
                         "eligible set (well under 1,000).")
    args = ap.parse_args()

    docs = REPO / "docs"

    import contextlib
    import os
    lock = (contextlib.nullcontext() if args.dry_run
            else board_lock(REPO, owner="robeson_alexander_ustaxdata_backfill"))
    with lock:
        candidates, total_rows, ambiguous = _collect_candidates(docs)
        print(f"board rows streamed: {total_rows:,}")
        print(f"Robeson+Alexander NC eligible candidates (ustaxdata-reachable, not yet "
              f"checked): {len(candidates):,}")
        if ambiguous:
            print(f"excluded as ambiguous-identity (shared dedupe_key with another candidate, "
                  f"never guessed at): {ambiguous:,}")

        before = {key: (dict(li.raw) if isinstance(li.raw, dict) else {}, li.tax_value)
                 for key, li in candidates.items()}

        listings = list(candidates.values())
        batch_stats = []
        if listings:
            print(f"\n=== Robeson+Alexander NC: running the real ustaxdata -> "
                  f"ustaxdata_multiyear -> tax_owed -> tax_aging chain in batches ===")
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

        # per-county breakdown, read off the listings' own county field (never a literal grep)
        by_county: dict[str, dict] = {}
        for li in listings:
            c = (li.county or "?").replace(" County", "").strip()
            d = by_county.setdefault(c, {"total": 0, "has_udt": 0, "multi_year": 0, "two_year": 0})
            d["total"] += 1
            raw = li.raw if isinstance(li.raw, dict) else {}
            if isinstance(raw.get("ustaxdata_delinquent_tax"), dict):
                d["has_udt"] += 1
            if raw.get("multi_year_delinquent_tax"):
                d["multi_year"] += 1
            if raw.get("two_year_delinquent"):
                d["two_year"] += 1
        print(f"\nper-county after this run: {by_county}")

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
            patches, {"robeson_alexander_ustaxdata_backfill": len(patches), "ambiguous": ambiguous},
            docs_dir=docs)
        print(f"\nwrote board: patched {stats_patch['applied']:,}/{len(patches):,} rows "
              f"(existing board: {stats_patch['existing']:,}, not_found: "
              f"{stats_patch['not_found']:,}, duplicate_key_matches: "
              f"{stats_patch['duplicate_key_matches']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
