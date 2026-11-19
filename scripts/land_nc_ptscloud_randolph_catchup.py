#!/usr/bin/env python3
"""One-time landing: run NCPtsCloudDelinquentTax's EXACT production tenant-fetch
(_download_delinquent_csv + _parse_csv, unmodified) for just the Randolph NC
tenant, and append the genuinely-new listings onto the board.

WHY THIS EXISTS (round-40 gap-matrix build-bucket sweep, 2026-11-18)

    nc_ptscloud_delinquent_tax.py is a normal, fully-wired production scraper
    (main.py's SCRAPER_MODULES, "counties_nc.nc_ptscloud_delinquent_tax") that
    sweeps all 17 Farragut bcpwa.ncptscloud.com tenants every run. Its own
    module comment, written 2026-07-01, documents 9 of those 17 tenants
    (Rutherford/Burke/Cumberland/Durham/Hertford/Mecklenburg/Randolph/Stokes/
    Wayne) as "valid tenants standing by with no export blob yet... light up
    automatically when their county posts a fresh extract" -- i.e. a genuine
    no-data-yet wait, not a bug, confirmed again live this round for 8 of the
    9 (Mecklenburg/Cumberland/Durham/Wayne/Burke/Rutherford/Stokes/Hertford
    all still answer an empty blob list today).

    Randolph is the one exception: a live GetTaxpayerDownloadList probe this
    round found it NOW has a real delinquent-export blob
    ("BillPWA/TaxpayerDownloads/Delinquent Export/DelinquentExtract.csv",
    8.2MB) that did not exist when the tenant list was last verified. The
    normal fetch() will pick this up automatically next time the full
    production pipeline actually runs this scraper -- but exactly like
    tonight's two heir_estate catch-ups (SC parcel_cache, commit 8e6e35a2; NC
    statewide-fallback, commit ac8224b4), nothing says that run has actually
    happened since the blob appeared, so this one-off direct call lands the
    real rows now instead of waiting on the next natural cycle.

    Dry-run verified live: parsed 1,606 real candidate listings from the
    production CSV parser; 288 are genuinely new against the board's existing
    6,046 Randolph NC rows (the rest already match an existing row's dedupe
    key, expected overlap with other tax/GIS sources already covering this
    county).

BOARD I/O: board_stream.iter_board_rows() (read-only streaming existing-keys
    scan) + web_artifact.append_new_rows() (dedupe_key()-keyed, append-only --
    these are NEW motivated-seller leads, not enrichment of existing rows),
    the same convention this session's other land_*.py scripts use at this
    board's size. Never load_board()/write_artifact().

    .venv/bin/python scripts/land_nc_ptscloud_randolph_catchup.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 \\
        .venv/bin/python scripts/land_nc_ptscloud_randolph_catchup.py --allow-large
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
from foreclosure_scraper.scrapers.counties_nc.nc_ptscloud_delinquent_tax import (  # noqa: E402
    _download_delinquent_csv, _parse_csv,
)
from foreclosure_scraper.web_artifact import (  # noqa: E402
    append_new_rows, board_lock, board_patch_size_state,
)

_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")

#: The ptscloud tenant this round's gap-matrix sweep confirmed now has a live
#: export blob but has never had a row land. Extend this tuple (not the
#: logic) for the next tenant a future sweep clears the same way -- matches
#: the convention land_nc_heir_estate_statewide_fallback.py's TARGET_COUNTIES
#: already set.
TARGET_TENANTS: tuple[str, ...] = ("Randolph",)


def _dedupe_key(li: Listing) -> str | None:
    try:
        return li.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


async def _collect(tenants: tuple[str, ...]) -> list[Listing]:
    out: list[Listing] = []
    async with client(timeout=30.0) as http:
        for tenant in tenants:
            text = await _download_delinquent_csv(http, tenant)
            if text is None:
                print(f"  {tenant}: no export blob (tenant_empty) -- skipped")
                continue
            rows = _parse_csv(text, tenant, "NC", tenant)
            print(f"  {tenant}: {len(rows)} real listings from the production parser")
            out.extend(rows)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--tenants", nargs="+", default=None,
                    help="Override TARGET_TENANTS (bare NC ptscloud tenant names).")
    args = ap.parse_args()

    tenants = tuple(args.tenants) if args.tenants else TARGET_TENANTS

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1
        if args.allow_large:
            os.environ["BOARD_PATCH_ALLOW_LARGE"] = "1"
            os.environ["BOARD_APPEND_ALLOW_LARGE"] = "1"

    print(f"querying the production NCPtsCloudDelinquentTax tenant path for: {', '.join(tenants)}")
    listings = asyncio.run(_collect(tenants))
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

    with board_lock(REPO, owner="land_nc_ptscloud_randolph_catchup", wait=900, poll=10):
        stats = append_new_rows(
            new_listings, {"counties_nc.nc_ptscloud_delinquent_tax (Randolph catch-up)":
                           len(new_listings)},
            docs_dir=docs_dir)
    print(f"append_new_rows: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
