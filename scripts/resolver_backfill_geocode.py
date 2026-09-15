#!/usr/bin/env python3
"""Safe geocode backfill for every board row missing lat/lon.

2026-09-15: found the existing `scripts/geocode_catchup.py` writes directly
to listings.json.gz with a raw json.dump() -- it bypasses board_lock() AND
load_board()/write_artifact(). load_board()'s own docstring warns exactly
about this: "Any incremental board-writer that reads listings.json directly
and re-runs write_artifact would drop that detail [comps/vision sidecar]."
Running the original script as-is would have silently wiped the heavy
comps/vision detail sidecar for every row on the board, not just the ones
being geocoded. This script reuses geocode_catchup.py's free Census batch
geocoder + county-centroid fallback logic, but goes through the same
load_board()/board_lock()/write_artifact() discipline every other board
write this session has used, and checkpoints progress every N batches so a
long run doesn't lose work if interrupted.

Census batch geocoder: free, no key, 950 addresses/request (Census 1000
limit, stay under). ~112 batches for the ~105K addressable backlog.

    python scripts/resolver_backfill_geocode.py --dry-run
    python scripts/resolver_backfill_geocode.py
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import re
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402

CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
BATCH_SIZE = 950
CHECKPOINT_EVERY = 10  # batches (~9,500 addresses) between board writes

# County-seat centroids (lat, lon) -- last-resort fallback for rows the
# Census geocoder can't match, or rows with no address at all but a known
# county. Reused verbatim from scripts/geocode_catchup.py.
COUNTY_SEATS = {
    "NC:Buncombe": (35.5951, -82.5515), "NC:Henderson": (35.3185, -82.4609),
    "NC:Rutherford": (35.2654, -81.9646), "NC:McDowell": (35.6208, -82.2096),
    "NC:Transylvania": (35.2246, -82.7346), "NC:Burke": (35.7476, -81.7043),
    "NC:Polk": (35.2382, -82.1990), "NC:New Hanover": (34.1808, -77.9462),
    "NC:Brunswick": (33.8908, -78.2569), "NC:Cleveland": (35.2330, -81.3406),
    "NC:Gaston": (35.2657, -81.1812), "NC:Lincoln": (35.4737, -81.2198),
    "NC:Catawba": (35.5512, -81.2234), "NC:Alexander": (35.8260, -81.1848),
    "NC:Iredell": (35.5926, -80.8823), "NC:Watauga": (36.1940, -81.6657),
    "NC:Avery": (36.0920, -81.8668), "NC:Mitchell": (35.9150, -82.1582),
    "NC:Yancey": (35.7390, -82.2982), "NC:Madison": (35.7390, -82.5620),
    "NC:Mecklenburg": (35.2271, -80.8431), "NC:Wake": (35.7796, -78.6382),
    "NC:Onslow": (34.7157, -77.4405), "NC:Carteret": (34.7182, -76.7185),
    "NC:Dare": (35.9410, -75.6760), "NC:Pender": (34.5257, -77.9414),
    "NC:Beaufort": (35.5424, -76.8397),
    "SC:Spartanburg": (34.9496, -81.9321), "SC:Greenville": (34.8526, -82.3940),
    "SC:Pickens": (34.8680, -82.7046), "SC:Anderson": (34.5034, -82.6501),
    "SC:Oconee": (34.6821, -83.1138), "SC:Cherokee": (35.0154, -81.6115),
    "SC:Union": (34.7154, -81.6248), "SC:Laurens": (34.4999, -81.9662),
    "SC:Charleston": (32.7765, -79.9311), "SC:Berkeley": (33.2160, -80.0245),
    "SC:Horry": (33.8361, -79.0165), "SC:Georgetown": (33.3768, -79.2951),
    "SC:Colleton": (32.7871, -80.5648), "SC:Beaufort": (32.4310, -80.6698),
    "SC:Williamsburg": (33.6743, -79.6853), "SC:Sumter": (33.9204, -80.3414),
    "SC:Darlington": (34.3006, -79.8756),
}


def _clean(v) -> str:
    # Found 2026-09-15: 377 board rows (all liensnc) carry a literal
    # embedded newline in street_address (a PDF-text-extraction artifact
    # where a wrapped line was never rejoined, e.g. "12\nTBD Taylor Lane").
    # A raw newline mid-CSV-row silently corrupts the whole Census batch
    # upload -- the server rejects the entire ~950-address file as
    # "malformed", not just that one row. Collapse all whitespace
    # defensively so one bad address can't sink an entire batch.
    return re.sub(r"\s+", " ", (v or "")).strip()


def build_address_string(li) -> str | None:
    addr = _clean(li.street_address)
    if not addr:
        return None
    city = _clean(li.city)
    state = _clean(li.state)
    zip_code = _clean(li.zip_code)
    return f"{addr}, {city}, {state} {zip_code}".strip()


def geocode_batch_census(addresses: list[str]) -> dict[str, tuple[float, float]]:
    results: dict[str, tuple[float, float]] = {}
    lines = []
    for i, addr_str in enumerate(addresses):
        parts = addr_str.split(", ")
        street = parts[0] if parts else ""
        city = parts[1] if len(parts) > 1 else ""
        state_zip = parts[2] if len(parts) > 2 else ""
        state = state_zip.split()[0] if state_zip else ""
        zip_code = state_zip.split()[1] if len(state_zip.split()) > 1 else ""
        # Escape embedded commas/quotes -- addresses can carry them (unit
        # numbers like "123 Main St, Apt B" already split correctly above,
        # but a raw comma inside a single field would misalign columns).
        def esc(s):
            return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s
        lines.append(f"{i},{esc(street)},{esc(city)},{esc(state)},{esc(zip_code)}")

    csv_data = "\n".join(lines)
    try:
        files = {"addressFile": ("addrs.csv", csv_data, "text/csv")}
        data = {"benchmark": "Public_AR_Current", "vintage": "Current_Current", "format": "csv"}
        r = httpx.post(CENSUS_BATCH_URL, data=data, files=files, timeout=180.0)
        if r.status_code != 200:
            print(f"  [http {r.status_code}] {r.text[:200]}")
            return results
        reader = csv.reader(io.StringIO(r.text))
        for row in reader:
            if len(row) < 6:
                continue
            idx_str = row[0].strip('"')
            status = row[2].strip('"')
            if status != "Match":
                continue
            coords_str = row[5].strip('"')
            if "," not in coords_str:
                continue
            lon_str, lat_str = coords_str.split(",")
            try:
                lon, lat, idx = float(lon_str), float(lat_str), int(idx_str)
                if 0 <= idx < len(addresses):
                    results[addresses[idx]] = (lat, lon)
            except (ValueError, IndexError):
                continue
    except Exception as e:
        print(f"  [error] {e!r}")
    return results


def centroid_fallback(li) -> tuple[float, float] | None:
    key = f"{li.state or ''}:{(li.county or '').strip()}"
    return COUNTY_SEATS.get(key)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="Cap total addresses processed (testing)")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="resolver_backfill_geocode")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        no_geo = [li for li in rows if not li.latitude or not li.longitude]
        with_addr = [li for li in no_geo if build_address_string(li)]
        without_addr = [li for li in no_geo if not build_address_string(li)]
        print(f"missing lat/lon: {len(no_geo):,} "
              f"({len(with_addr):,} geocodable, {len(without_addr):,} centroid-only)")

        if args.limit:
            with_addr = with_addr[: args.limit]
            print(f"--limit applied: processing {len(with_addr):,} addresses")

        geocoded = centroided = failed = 0
        batches = [with_addr[i:i + BATCH_SIZE] for i in range(0, len(with_addr), BATCH_SIZE)]
        for bi, batch in enumerate(batches, 1):
            pairs = [(li, build_address_string(li)) for li in batch]
            addresses = [addr for _, addr in pairs]
            print(f"batch {bi}/{len(batches)}: {len(addresses)} addresses...", flush=True)
            results = geocode_batch_census(addresses)
            print(f"  matched: {len(results)}/{len(addresses)}", flush=True)

            for li, addr in pairs:
                if addr in results:
                    lat, lon = results[addr]
                    li.latitude, li.longitude = lat, lon
                    if not isinstance(li.raw, dict):
                        li.raw = {}
                    li.raw["geo_imprecise"] = "census_geocode"
                    geocoded += 1
                else:
                    c = centroid_fallback(li)
                    if c:
                        li.latitude, li.longitude = c
                        if not isinstance(li.raw, dict):
                            li.raw = {}
                        li.raw["geo_imprecise"] = "county_centroid"
                        centroided += 1
                    else:
                        failed += 1

            if bi % CHECKPOINT_EVERY == 0 and not args.dry_run:
                write_artifact(rows, {"resolver_backfill_geocode_checkpoint": geocoded + centroided},
                               docs_dir=REPO / "docs")
                print(f"  [checkpoint] wrote board at batch {bi}/{len(batches)} "
                      f"({geocoded} geocoded, {centroided} centroided so far)", flush=True)

            if bi < len(batches):
                time.sleep(2)

        for li in without_addr:
            c = centroid_fallback(li)
            if c:
                li.latitude, li.longitude = c
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["geo_imprecise"] = "county_centroid_no_addr"
                centroided += 1
            else:
                failed += 1

        print(f"\n=== RESULTS ===")
        print(f"census geocoded: {geocoded:,}")
        print(f"centroid fallback: {centroided:,}")
        print(f"failed (no data): {failed:,}")
        still_missing = sum(1 for li in rows if not li.latitude or not li.longitude)
        print(f"still missing lat/lon board-wide: {still_missing:,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        write_artifact(rows, {"resolver_backfill_geocode": geocoded + centroided}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
