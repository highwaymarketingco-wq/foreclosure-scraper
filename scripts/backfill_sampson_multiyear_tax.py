#!/usr/bin/env python3
"""One-time backfill: land Sampson County NC's NEW multi-year-tax enrichment
(enrichment_sampson_multiyear_tax.py, round 59) onto the already-published board.

WHY THIS EXISTS. gap_matrix's 2026-11-19 "sourced-not-built" sweep found Sampson NC's
    two_year_delinquent / tax_aging_surfaced / multi_year_delinquent_tax all unbuilt (1,016
    applicable rows each, source "tax/property card: sampsonnc.munisselfservice.com") -- despite
    verification/verifiers/tax_lien_munis.py's own PORTALS dict having PROVEN Sampson's Tyler
    Munis "Citizen Self Service" portal live and working back on 2026-10-29/11-12 (search()
    confirmed against 3 real board parcels, 19-21 real bill rows each). The verifier alone only
    CONFIRMS/REFUTES a claim a row already carries from some other producer; 0/1,016 Sampson rows
    carry any such claim (board_stream-measured 2026-11-19), so it had nothing to act on. This
    script runs the NEW enrich_with_sampson_multiyear_tax() (reuses tax_lien_munis.search()/
    view() directly, same low-risk path enrichment_pender_multiyear_tax.py already took for the
    same reason) against real board rows and lands the result.

SCOPE OF THIS FIRST RUN: a DELIBERATELY SMALL, real pilot (enrichment_sampson_multiyear_tax.py's
    own SAMPSON_MYDT_MAX default is 40, not the full 349-row eligible set) -- this portal has
    never been hit by this project at ANY volume, and tax_lien_munis's shared-session design
    means CONCURRENCY must stay 1, so a first pass measures real qualify-rate/fetch-error-rate
    before anyone raises the cap.

PHASE 2.5 (same trick backfill_multiyear_tax_wake_randolph.py's own Phase 2.5 established
    2026-10-21): any row that qualifies for multi_year_delinquent_tax this run also gets
    enrich_tax_owed()/enrich_tax_aging() run over it (PURE, no extra network) so its
    tax_aging_surfaced cell closes in the SAME patch, for free.

BOARD I/O: board_stream.iter_board_rows() (read-only streaming scan) + web_artifact.
    patch_existing_rows() (dedupe_key()-keyed collision guard), same convention as every other
    backfill script this project uses on this board size -- never load_board()/write_artifact().

Usage:
    .venv/bin/python3 scripts/backfill_sampson_multiyear_tax.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python3 scripts/backfill_sampson_multiyear_tax.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_sampson_multiyear_tax import (  # noqa: E402
    CHECKED_KEY, MYDT_KEY, TYD_KEY, enrich_with_sampson_multiyear_tax,
)
from foreclosure_scraper.enrichment_tax_aging import enrich_tax_aging  # noqa: E402
from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.verification.verifiers import _tax_common as tc  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

COUNTY = "Sampson"  # NC-only on this board; not in DUAL_STATE_COUNTIES
_WATCH_KEYS =(MYDT_KEY, TYD_KEY, CHECKED_KEY, "tax_owed", "tax_aging_surfaced", "tax_aging_high")
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")


def _county_key(county: str) -> str:
    return (county or "").replace(" County", "").strip().lower()


def _dedupe_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="Cap patches (testing)")
    args = ap.parse_args()

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="backfill_sampson_multiyear_tax", wait=3600, poll=10)

    with lock:
        print(f"\n[{time.strftime('%H:%M:%S')}] scanning board...", flush=True)
        key_counts: Counter = Counter()
        candidates: dict[str, Listing] = {}
        row_meta: dict[str, dict] = {}  # dedupe_key -> original raw
        scanned = 0
        total_sampson = 0
        already_have = 0

        for rec in iter_board_rows(docs / "listings.json.gz"):
            scanned += 1
            key = _dedupe_key(rec)
            if key is not None:
                key_counts[key] += 1
            if str(rec.get("state") or "").strip().upper() != "NC":
                continue
            if _county_key(rec.get("county") or "") != COUNTY.lower():
                continue
            total_sampson += 1
            raw = rec.get("raw") or {}
            if isinstance(raw.get(MYDT_KEY), dict) or isinstance(raw.get(TYD_KEY), dict) or raw.get(CHECKED_KEY):
                already_have += 1
                continue
            pid = str(rec.get("parcel_id") or "").strip()
            if not pid or not tc.alnum(pid):
                continue
            if key is None:
                continue
            li = Listing.model_construct(
                parcel_id=pid, county=rec.get("county") or COUNTY, state="NC",
                address=rec.get("address") or "",
                source=rec.get("source") or "board", source_url=rec.get("source_url") or "",
                raw=dict(raw))
            candidates[key] = li
            row_meta[key] = raw

        print(f"scanned {scanned:,} board rows")
        print(f"Sampson,NC total: {total_sampson:,}  already-checked-or-qualified: {already_have:,}  "
              f"eligible-for-this-run (has parcel_id): {len(candidates):,}")

        listings = list(candidates.values())
        print(f"\nrunning enrich_with_sampson_multiyear_tax() against up to "
              f"{len(listings):,} candidates (module's own MAX_ROWS caps the live-fetch count)...")
        stats = asyncio.run(enrich_with_sampson_multiyear_tax(listings))
        print(f"enrich_with_sampson_multiyear_tax stats: {stats}")

        qualified = [li for li in listings if isinstance(li.raw, dict) and isinstance(li.raw.get(MYDT_KEY), dict)]
        print(f"\nPhase 2.5: restating tax_owed/tax_aging_surfaced over "
              f"{len(qualified):,} multi_year_delinquent_tax-qualified rows (pure, no network)...")
        if qualified:
            owed_stats = enrich_tax_owed(qualified)
            aging_stats = enrich_tax_aging(qualified)
            print(f"  enrich_tax_owed: {dict(owed_stats) if hasattr(owed_stats, 'items') else owed_stats}")
            print(f"  enrich_tax_aging: {dict(aging_stats) if hasattr(aging_stats, 'items') else aging_stats}")

        patches: dict[str, dict] = {}
        collisions = 0
        for key, li in candidates.items():
            if key_counts[key] > 1:
                collisions += 1
                continue
            after_raw = li.raw if isinstance(li.raw, dict) else {}
            before_raw = row_meta[key]
            raw_patch = {k: after_raw.get(k) for k in _WATCH_KEYS if after_raw.get(k) != before_raw.get(k)}
            if not raw_patch:
                continue
            if args.limit and len(patches) >= args.limit:
                continue
            patches[key] = {"raw": raw_patch}

        print(f"\ncollisions dropped (dedupe_key shared with another board row): {collisions:,}")
        print(f"total patches ready: {len(patches):,}")
        n_two_year = sum(1 for p in patches.values() if TYD_KEY in p["raw"])
        n_multi = sum(1 for p in patches.values() if MYDT_KEY in p["raw"])
        n_checked_only = sum(1 for p in patches.values()
                             if set(p["raw"]) == {CHECKED_KEY})
        print(f"  carrying two_year_delinquent: {n_two_year:,}")
        print(f"  carrying multi_year_delinquent_tax (qualified): {n_multi:,}")
        print(f"  checked-only (no usable grid found): {n_checked_only:,}")

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
            return 0

        result = patch_existing_rows(
            patches,
            {"backfill_sampson_multiyear_tax": f"{len(patches)} Sampson NC rows"},
            docs_dir=docs)
        print("\n=== patch_existing_rows result ===")
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
