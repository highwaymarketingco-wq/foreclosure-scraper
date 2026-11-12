#!/usr/bin/env python3
"""One-time backfill: derive raw['tax_owed'] / raw['tax_aging_surfaced'] for Cabarrus NC rows
that ALREADY carry real multi-year tax-bill history from enrichment_cabarrus_multiyear_tax.py's
793/793 backfill (2026-10-29), but never got the two DOWNSTREAM derivation passes applied.

WHY THIS EXISTS (gap_matrix "Cabarrus tax_aging_surfaced sourced-not-built", 2,920 est rows).
    Checked first (per this task's own brief) for a prior Cabarrus tax enrichment file to extend
    rather than duplicate: enrichment_cabarrus_multiyear_tax.py already exists and already IS the
    tax.cabarruscounty.us reader -- its own docstring says raw['multi_year_delinquent_tax'] is
    "byte-shape-compatible" with the Catawba/Wake/Randolph/Gaston blocks so that
    enrichment_tax_owed.py's FIELD_PRIORITY promotes it into raw['tax_owed'] ->
    raw['tax_aging_surfaced'] (enrichment_tax_aging.py) "for free". Writing a second
    tax.cabarruscounty.us fetcher here would be a pure duplicate -- the live source is already
    read and already landed on the board. No new fetcher file was created for that reason.

    Confirmed live against the real board (board_stream, 2026-11-05, read-only):
        2,920 total Cabarrus NC rows / 793 with a parcel_id the itsnet module could search
        634 carry raw['two_year_delinquent'] (634 real, answered searches; 629 of those are
            genuinely CLEAN -- is_two_year_plus=False, nothing to surface)
          5 carry raw['multi_year_delinquent_tax'] (real repeat delinquency, $523-$15,776 owed,
            2-10 matured years late -- two of the five are counties_nc.nc_heir_estate_parcels
            heir/estate leads)
          0 carry raw['tax_owed']
          0 carry raw['tax_aging_surfaced']
    So the "for free" promotion the module's docstring describes has never actually run against
    these rows: backfill_cabarrus_multiyear_tax.py (the script that landed the 793/793 data)
    writes {"raw": li.raw} straight to the board via patch_existing_rows() and never also calls
    enrich_tax_owed()/enrich_tax_aging() first -- unlike a FRESH scrape inside main.py's regular
    cycle, where the same `enriched` list is threaded through enrich_with_cabarrus_multiyear_tax()
    THEN enrich_tax_owed() THEN enrich_tax_aging() in one pass (main.py ~line 3731-3778). A
    one-time board patch that bypasses the rest of that cycle gets the raw tax-bill data but
    never the derived fields, and these specific rows are never "freshly scraped" again for a
    later cycle to catch.

    PROVED in-memory (no network, no board write, /tmp script) 2026-11-05: loading the 5 real
    multi_year_delinquent_tax rows and calling the EXISTING, UNMODIFIED enrich_tax_owed() +
    enrich_tax_aging() over them derives a correct raw['tax_owed'] and raw['tax_aging_surfaced']
    for all 5 (years_delinquent 2-10, tax_aging_high=True on every one) -- e.g. parcel
    56119157830000 (BARBER BEATRICE M ESTATE): tax_owed.balance=3308.07,
    tax_aging_surfaced={years_delinquent:10, status:'delinquent', ...}. This is NOT a new
    enrichment algorithm -- it is exactly the bridge the module's own docstring already claims,
    just never applied to this one-time-backfilled slice of the board.

    This is a narrower, Cabarrus-specific instance of the SAME shape flagged in
    project_iredell_tax_aging_architecture_gap_2026-10-29 (where the separate discovery scraper
    never retroactively touches pre-existing rows) -- but Cabarrus's own module already implements
    the "write it so FIELD_PRIORITY promotes it generically" design (unlike Iredell's reliance on a
    second scraper), so this one case is a plain backfill-completeness gap, safe to close in
    isolation: it only ever WRITES raw['tax_owed']/raw['tax_aging_surfaced'] from a block that is
    already, verifiably, this row's own real tax-bill answer, using the project's own existing,
    tested derivation code verbatim.

    REALISTIC CEILING: the gap_matrix "2,920 est rows affected" figure is the full Cabarrus
    population scanned for this signal, not a promise of 2,920 real positives -- most Cabarrus
    properties are not 2+ years tax-delinquent. The real, honest yield today is the 5 rows above;
    this script's main value is PERMANENT: it will also pick up every future Cabarrus row that
    enrich_with_cabarrus_multiyear_tax() (run by backfill_cabarrus_multiyear_tax.py, or a future
    pipeline cycle) qualifies for multi_year_delinquent_tax, including the 2,127 Cabarrus rows that
    currently have no parcel_id at all and the ~133-159 parcel_unresolvable ones, if either is ever
    fixed by other work (parcel_cache backfill, etc.) -- none of that is this script's job.

BOARD I/O: board_stream.iter_board_rows() once (read-only), then patch_existing_rows() under
    board_lock(), same discipline as backfill_cabarrus_multiyear_tax.py -- never
    load_board()/write_artifact(). Only touches a row whose raw actually changed (new tax_owed
    and/or tax_aging_surfaced); a row enrich_tax_owed()/enrich_tax_aging() leave alone is not
    patched at all.

GATE: no live network call exists in this script at all (CABARRUS_TAX_AGING_BACKFILL is a
    convenience kill switch for the WRITE path only, matching this repo's "every enrichment is
    gated" convention -- there is nothing to gate on the read/derive side, which is pure, free,
    offline recomputation of enrichment_tax_owed.py/enrichment_tax_aging.py's own existing logic).

Usage:
    python scripts/backfill_cabarrus_tax_aging.py --dry-run
    python scripts/backfill_cabarrus_tax_aging.py --allow-large
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_tax_aging import enrich_tax_aging  # noqa: E402
from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, board_lock, board_patch_size_state, patch_existing_rows,
)

ENABLED = os.environ.get("CABARRUS_TAX_AGING_BACKFILL") != "0"

_IS_CABARRUS = lambda rec: (
    str(rec.get("county") or "").strip().lower() == "cabarrus"
    and str(rec.get("state") or "").upper() == "NC"
)


def _candidates(docs_dir: Path) -> list[Listing]:
    """Cabarrus rows with a real multi_year_delinquent_tax block (the only block shape that
    carries a _GENERIC_KEYS amount enrich_tax_owed's Pass B can read) that have not yet been
    surfaced. two_year_delinquent-only rows are skipped on purpose: that block has no amount
    field at all (is_two_year_plus/years/oldest_year/source), so running the two real passes on
    them is a guaranteed no-op -- confirmed by the Pass B key scan in enrichment_tax_owed.py."""
    out = []
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        if not _IS_CABARRUS(rec):
            continue
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if not isinstance(raw.get("multi_year_delinquent_tax"), dict):
            continue
        if isinstance(raw.get("tax_aging_surfaced"), dict):
            continue  # already surfaced (idempotent re-run)
        li = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS if k in rec})
        li.raw = dict(raw)
        out.append(li)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    args = ap.parse_args()

    if not ENABLED:
        print("CABARRUS_TAX_AGING_BACKFILL=0 -- disabled.")
        return 0

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"

    targets = _candidates(docs_dir)
    print(f"Cabarrus rows eligible (multi_year_delinquent_tax present, tax_aging_surfaced "
          f"absent): {len(targets)}")
    if not targets:
        print("nothing to do.")
        return 0

    owed_stats = enrich_tax_owed(targets)
    aging_stats = enrich_tax_aging(targets)
    print("enrich_tax_owed:", owed_stats)
    print("enrich_tax_aging:", aging_stats)

    patches: dict[str, dict] = {}
    for li in targets:
        if isinstance(li.raw.get("tax_aging_surfaced"), dict):
            patches[li.dedupe_key()] = {"raw": li.raw}

    print(f"\npatches staged: {len(patches)}")
    for key, patch in list(patches.items())[:5]:
        print(" ", key, "->", patch["raw"].get("tax_aging_surfaced"))

    if args.dry_run:
        print("\nDRY RUN -- nothing written.")
        return 0

    if not patches:
        print("nothing to write.")
        return 0

    with board_lock(REPO, owner="cabarrus_tax_aging_backfill"):
        stats = patch_existing_rows(patches, {"cabarrus_tax_aging_backfill": len(patches)},
                                     docs_dir=docs_dir)
        print("patch_existing_rows:", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
