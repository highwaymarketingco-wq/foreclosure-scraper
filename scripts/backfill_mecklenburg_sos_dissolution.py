#!/usr/bin/env python3
"""Mecklenburg NC 'sos_dissolution' catch-up: run the REAL, unmodified enrich_with_sos_
dissolution() (src/foreclosure_scraper/enrichment_sos_dissolution.py) over Mecklenburg's
never-screened LLC/Inc defendant rows, in bounded rounds that respect the function's own
900s wall-clock budget and 5-consecutive-failure circuit breaker.

WHY THIS EXISTS (gap-matrix follow-up, 2026-11-10, "sos_dissolution" built-but-low-yield)
    enrich_with_sos_dissolution() already has a correct negative-write path (writes
    raw['sos_screen'] for a completed "active"/"unknown" lookup, fixed 2026-10-16/17 to a
    SEPARATE key from the positive raw['sos_dissolution'] so a clean entity can never be
    misread as dissolved -- verified live by reading gap_matrix.py's checked_columns():
    `if raw.get("sos_agent") or raw.get("sos_dissolution") or raw.get("sos_screen")`).
    What was never done is a historical catch-up: like tax_aging_surfaced/gis_attrs/
    bop_federal before it, this enricher is only ever called from main.py's run tail
    against that run's OWN `enriched` list -- a row whose defendant qualified on an earlier
    run and was never re-touched since can sit with the precondition satisfied indefinitely.
    Measured 2026-11-10: of Mecklenburg's 39,861 rows, 5,268 have a business-type defendant
    name (name_normalize.is_entity(), the same word-boundary-safe check this enricher uses
    internally) and NC state; only 158 have ever been screened by this producer
    (sos_agent/sos_dissolution/sos_screen) -- leaving roughly 5,110 never-checked rows.

A REAL LIVE SCRAPE, NOT CHEAP. NC SOS (sosnc.gov) sits behind Cloudflare; this enricher
uses Scrapling stealth rendering (~10-30s/lookup), concurrency=2, a hard 900s wall-clock
budget (SOS_MAX_SECONDS) and a 5-consecutive-failure circuit breaker that bails the whole
call if SOS starts blocking -- all left untouched here, per this round's own discipline of
never bypassing an existing safety cap. One realistic call clears roughly 60-120 UNIQUE
business names before the budget/breaker stops it, not the whole backlog at once.

THE REAL AMPLIFICATION THIS SCRIPT ADDS (not a change to the enricher itself): enrich_with_
sos_dissolution() dedupes by name BEFORE it ever queries -- of two rows sharing the exact
same defendant ("SMITH FAMILY LLC" owning two parcels), only the FIRST one in the list it is
given is ever looked up or stamped; the enricher has no cross-row propagation of its own.
This script groups Mecklenburg's never-checked candidates by normalized defendant name,
sends exactly ONE representative row per name into the real function (so the live-lookup
budget is spent once per distinct entity, never twice on a name already known), then
propagates the SAME result (the same LLC has the same dissolution status regardless of
which parcel it owns) to every sibling row sharing that name. Measured 2026-11-10: 5,268
candidate rows collapse to 4,674 distinct names (1.13 rows/name) -- a modest but real
amplification of each live lookup.

BOARD I/O: Pass 1 streams the whole board once (board_stream.iter_board_rows(), never
load_board()) to tally dedupe_key() collisions AND collect never-checked Mecklenburg
business-defendant rows grouped by normalized name. Pass 2 runs the REAL enrich_with_sos_
dissolution() on one representative Listing per name. Pass 3 propagates + patches via
web_artifact.patch_existing_rows(), checkpointed per round.

    python scripts/backfill_mecklenburg_sos_dissolution.py --dry-run
        # candidate-count only: NO live network calls, NO writes.
    python scripts/backfill_mecklenburg_sos_dissolution.py --rounds 1
        # one real ~900s round (orchestrating session only; needs the board lock).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_sos_dissolution import (  # noqa: E402
    enrich_with_sos_dissolution,
)
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.name_normalize import is_entity  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")
_LIGHT_FIELDS = _SIG_FIELDS + ("defendant", "source")
_SOS_KEYS = ("sos_agent", "sos_dissolution", "sos_screen", "sos_status")
_ALREADY_CHECKED_KEYS = ("sos_agent", "sos_dissolution", "sos_screen")


def _dedupe_key(rec: dict) -> Optional[str]:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Candidate-count only: no live network calls, no writes.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Stop scanning after this many board rows (testing)")
    ap.add_argument("--rounds", type=int, default=1,
                    help="How many ~900s enrich_with_sos_dissolution() rounds to run this "
                         "invocation (each round re-picks never-yet-checked names)")
    ap.add_argument("--max-check", type=int, default=200,
                    help="Passed straight to enrich_with_sos_dissolution()'s own max_check "
                         "(unique names); its own 900s budget/breaker bounds real runtime "
                         "regardless of this ceiling")
    args = ap.parse_args()

    docs = REPO / "docs"

    print("pass 1/3: streaming the full board for dedupe-collision tally + "
          "Mecklenburg business-defendant candidate selection...")
    key_counts: Counter = Counter()
    by_name: dict[str, list[str]] = defaultdict(list)       # normalized name -> [dedupe_key, ...]
    rep_listing: dict[str, Listing] = {}                    # normalized name -> representative Listing
    scanned = 0
    meck_total = 0
    meck_business_nc = 0
    already_checked = 0
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
        if st == "NC" and co == "Mecklenburg":
            meck_total += 1
            defendant = rec.get("defendant")
            if defendant and is_entity(defendant):
                raw = rec.get("raw") or {}
                if any(raw.get(k) for k in _ALREADY_CHECKED_KEYS):
                    already_checked += 1
                elif key is not None:
                    meck_business_nc += 1
                    nm = defendant.strip().lower()
                    by_name[nm].append(key)
                    if nm not in rep_listing:
                        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
                        li.raw = {k: raw[k] for k in _SOS_KEYS if k in raw}
                        rep_listing[nm] = li
        if args.limit and scanned >= args.limit:
            break

    # Drop collision keys from every name group up front (never patch a non-unique identity).
    for nm, keys in list(by_name.items()):
        safe = [k for k in keys if key_counts[k] <= 1]
        if safe:
            by_name[nm] = safe
        else:
            del by_name[nm]
            rep_listing.pop(nm, None)

    print(f"scanned {scanned:,} board rows")
    print(f"Mecklenburg rows: {meck_total:,}")
    print(f"  already screened (sos_agent/sos_dissolution/sos_screen present): {already_checked:,}")
    print(f"  never-checked business-defendant NC rows: {meck_business_nc:,}")
    print(f"  distinct normalized defendant names among those: {len(by_name):,}")
    print(f"  (no dedupe key at all, board-wide: {skipped_no_key:,})")

    if args.dry_run:
        print("\nDRY RUN -- no live network calls made, nothing written.")
        return 0
    if not by_name:
        print("\nnothing to do.")
        return 0

    names_remaining = sorted(by_name)
    total_patched = 0
    total_dissolved = 0
    total_active_or_unknown = 0

    with board_lock(REPO, owner="backfill_mecklenburg_sos_dissolution"):
        for rnd in range(args.rounds):
            if not names_remaining:
                print(f"\n[round {rnd}] no names left to check this invocation.")
                break
            reps = [rep_listing[nm] for nm in names_remaining]
            before = {nm: dict(li.raw) for nm, li in zip(names_remaining, reps)}

            t0 = time.monotonic()
            print(f"\n[round {rnd}] running enrich_with_sos_dissolution() on "
                  f"{len(reps):,} candidate names (max_check={args.max_check}, "
                  f"its own 900s budget + 5-consecutive-fail breaker apply)...", flush=True)
            asyncio.run(enrich_with_sos_dissolution(reps, max_check=args.max_check))
            elapsed = time.monotonic() - t0

            patches: dict[str, dict] = {}
            checked_names: list[str] = []
            round_dissolved = 0
            round_active = 0
            for nm, li in zip(names_remaining, reps):
                after = li.raw if isinstance(li.raw, dict) else {}
                if after == before[nm]:
                    continue  # not reached this round (budget/breaker stopped early)
                checked_names.append(nm)
                is_dissolved = bool(after.get("sos_dissolution") or after.get("sos_agent"))
                if is_dissolved:
                    total_dissolved += 1
                    round_dissolved += 1
                else:
                    total_active_or_unknown += 1
                    round_active += 1
                update = {k: after[k] for k in _SOS_KEYS if k in after}
                for key in by_name[nm]:
                    patches[key] = {"raw": update}

            stats = patch_existing_rows(
                patches, {"backfill_mecklenburg_sos_dissolution": f"round={rnd}"},
                docs_dir=docs) if patches else {"applied": 0, "not_found": 0,
                                                "duplicate_key_matches": 0, "existing": None}
            total_patched += stats["applied"]
            names_remaining = [nm for nm in names_remaining if nm not in checked_names]
            print(f"  [round {rnd}] {elapsed:.0f}s | names actually checked: "
                  f"{len(checked_names)}/{len(reps)} | dissolved/admin-dissolved: "
                  f"{round_dissolved} | active/unknown: {round_active} "
                  f"| rows patched (incl. sibling parcels under the same name): "
                  f"{stats['applied']}/{len(patches)} "
                  f"(not_found: {stats['not_found']}, "
                  f"duplicate_key_matches: {stats['duplicate_key_matches']})", flush=True)
            if len(checked_names) < len(reps):
                print(f"  budget/breaker stopped this round early -- "
                      f"{len(reps) - len(checked_names)} names left for a future round.")

    print(f"\n=== RESULTS ===")
    print(f"rows patched (incl. sibling same-name parcels): {total_patched:,}")
    print(f"  distinct names resolved to dissolved/admin-dissolved: {total_dissolved:,}")
    print(f"  distinct names resolved to active/unknown (negative, now checked): "
          f"{total_active_or_unknown:,}")
    print(f"names still unchecked after this invocation: {len(names_remaining):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
