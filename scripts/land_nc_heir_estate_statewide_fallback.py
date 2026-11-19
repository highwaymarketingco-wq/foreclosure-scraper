#!/usr/bin/env python3
"""One-time landing: run NCHeirEstateParcels._process_county() (the EXACT production
path, unmodified) against a handful of NC statewide-fallback counties that gap_matrix
still flags heir_estate "sourced-not-built" for, and append the genuinely-new listings
onto the board.

WHY THIS EXISTS (round-38 gap-matrix build-bucket sweep, 2026-11-18)

    nc_heir_estate_parcels.py's own module docstring ("2026-11-16 FOLLOW-UP SWEEP")
    already investigated exactly this cell and found there is NO missing code and NO
    missing registry entry: Columbus/Alexander/Swain (plus Lenoir/Vance, since folded
    into their own fixes/left open) are covered correctly today by
    NC_STATEWIDE_FALLBACK_COUNTIES -- the statewide NC OneMap mirror has REAL,
    substantial decedent-titled owner-name data for all of them (live counts recorded
    there: Columbus 1,168, Vance 887, Swain 133, Alexander 50 heir/estate-pattern hits).
    That investigation's own conclusion: "a live board_stream audit this same day found
    0 rows ever published by this producer for any of these ... counties despite the
    real data above -- that gap ... is a run-cadence/orchestration question, not
    something a change to THIS module's county lists can fix."

    This script IS that missing run: NCHeirEstateParcels.fetch() always sweeps all 89
    statewide-fallback counties every time (a ~70-130s ArcGIS crawl per the class's own
    timeout comment), so the normal pipeline either never reaches completion for this
    producer or its results never got landed as a one-off historical catch-up -- the
    identical "correct and wired but never actually applied to the board" shape already
    fixed this session for SC heir_estate/parcel_cache (land_sc_heir_estate_parcel_cache.py,
    commit 8e6e35a2) and for ustaxdata_multiyear_tax/its_public_tax elsewhere. Calling
    _process_county() directly for just these few counties (instead of the full 89-county
    fetch()) avoids re-paying for the other ~85 counties' queries just to land these.

    gap_matrix today (2026-11-18, round 38) still reads Columbus (654 est_rows),
    Alexander (311), Swain (187) as "sourced-not-built" for heir_estate -- built=no,
    ran=False, meaning its own producer registry does not even credit a producer for
    this cell, despite nc_heir_estate_parcels.py's own docstring already confirming the
    mechanism and the live data. Vance is included too (same mechanism, zero extra
    network cost once the http client is open) even though gap_matrix currently scores
    it "built-not-verified" with a trivial est_rows=1 -- it is the exact same unlanded-
    rows situation per that module's own 2026-11-16 note, so landing its real rows here
    is free upside, not scope creep requiring a separate round.

    Lenoir is deliberately NOT included: it already got its OWN dedicated COUNTY_GIS
    entry today (commit 0a29a724), a different code path than this script exercises.

BOARD I/O: board_stream.iter_board_rows() (read-only streaming existing-keys scan) +
    web_artifact.append_new_rows() (dedupe_key()-keyed, append-only -- these are NEW
    motivated-seller leads, not enrichment of existing rows), the same convention
    land_sc_heir_estate_parcel_cache.py uses at this board's size. Never load_board()/
    write_artifact().

    .venv/bin/python scripts/land_nc_heir_estate_statewide_fallback.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 \
        .venv/bin/python scripts/land_nc_heir_estate_statewide_fallback.py --allow-large
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.http_client import client  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_nc.nc_heir_estate_parcels import (  # noqa: E402
    NCHeirEstateParcels, _NC_ONEMAP_SPEC,
)
from foreclosure_scraper.web_artifact import (  # noqa: E402
    append_new_rows, board_lock, board_patch_size_state,
)

_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")

#: The statewide-fallback counties this round's gap-matrix sweep confirmed are live
#: (real owner-name hits) but have never had a row land on the board. Extend this
#: tuple, not the logic, for the next county a future sweep clears the same way.
TARGET_COUNTIES: tuple[str, ...] = ("Columbus", "Alexander", "Swain", "Vance")


def _dedupe_key(li: Listing) -> str | None:
    try:
        return li.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


async def _collect(counties: tuple[str, ...]) -> list[Listing]:
    scraper = NCHeirEstateParcels()
    out: list[Listing] = []
    async with client(timeout=25.0) as http:
        for county in counties:
            rows = await scraper._process_county(http, "NC", county, _NC_ONEMAP_SPEC)  # noqa: SLF001
            print(f"  {county}: {len(rows)} real listings from the production path")
            out.extend(rows)
    print(f"run_stats: {scraper.run_stats}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--counties", nargs="+", default=None,
                    help="Override TARGET_COUNTIES (bare county names, NC only).")
    args = ap.parse_args()

    counties = tuple(args.counties) if args.counties else TARGET_COUNTIES

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"
            os.environ["BOARD_APPEND_ALLOW_LARGE"] = "1"

    print(f"querying the production NCHeirEstateParcels path for: {', '.join(counties)}")
    listings = asyncio.run(_collect(counties))
    print(f"classified {len(listings)} candidate listings total")
    if not listings:
        print("nothing to land.")
        return 0

    print("checking against existing board for already-known keys...")
    existing_keys: set[str] = set()
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
        key = _dedupe_key(light)
        if key:
            existing_keys.add(key)

    new_listings: list[Listing] = []
    seen: set[str] = set()
    for li in listings:
        key = _dedupe_key(li)
        if not key or key in existing_keys or key in seen:
            continue
        seen.add(key)
        new_listings.append(li)

    print(f"genuinely new (not already on board): {len(new_listings)} of {len(listings)}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for li in new_listings[:5]:
            print(" ", li.county, li.owner_name, li.parcel_id, li.street_address)
        return 0
    if not new_listings:
        print("nothing new to append.")
        return 0

    with board_lock(REPO, owner="land_nc_heir_estate_statewide_fallback", wait=900, poll=10):
        stats = append_new_rows(
            new_listings, {"counties_nc.nc_heir_estate_parcels (statewide fallback catch-up)":
                           len(new_listings)},
            docs_dir=docs_dir)
    print(f"append_new_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
