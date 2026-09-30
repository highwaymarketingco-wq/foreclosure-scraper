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

BOARD I/O REWRITE (2026-09-30, same pattern as resolver_backfill_parcel.py's
2026-09-29 rewrite and run_dew_lien_enrichment.py): this ran exactly once,
2026-09-15 (commit 81886a89, 58,559 Census-matched + 50,475 county-centroid,
against a 175,518-row / ~1.04 GB board) via load_board()/write_artifact() --
correct at the time. It has not run since, and re-running it as originally
written would now be refused or OOM this 8 GB Mac: the board has grown to
219,530+ rows, an estimated ~1.3 GB uncompressed source, over
BOARD_LOAD_MAX_SOURCE_MB's 1,200 MB load_board() ceiling (see
web_artifact.py; resolver_backfill_parcel.py's own docstring measured an
11.1 GB physical footprint trying to load a same-sized board). That ceiling,
not a code bug in the geocoding logic itself, is the entire reason this
population re-accumulated: every row landed by a new scraper since 9/15
that never got a coordinate (liensnc, nc_ecourts_lis_pendens,
nc_ptscloud_delinquent_tax, sc_public_index, and others) has had no safe way
to reach this script's Census-geocoding logic.

Fix: targets are collected by streaming the published board
(board_stream.iter_board_rows(), read-only, no lazy-detail sidecar -- this
enricher needs none of comps/vision/cama) instead of load_board(), and each
checkpoint lands via web_artifact.patch_existing_rows() (task_0658b33b
pattern) instead of write_artifact() with the whole board. The Census
batch-geocoding logic itself (geocode_batch_census, COUNTY_SEATS fallback,
_clean's embedded-newline guard) is UNCHANGED.

    python scripts/resolver_backfill_geocode.py --dry-run
    python scripts/resolver_backfill_geocode.py --limit 950   # small verified batch
    BOARD_PATCH_ALLOW_LARGE=1 scripts/with_board_lock.sh resolver_backfill_geocode -- \\
        .venv/bin/python scripts/resolver_backfill_geocode.py
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

#: Same identity fields web_artifact._APPEND_SIG_FIELDS keys patches on --
#: kept as a local literal rather than importing a private symbol (same
#: choice run_dew_lien_enrichment.py and resolver_backfill_parcel.py made).
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")

CHECKPOINT_EVERY = 10  # batches (~9,500 addresses) between board writes


def _engine_running() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", "--",
         r"run_local\.sh|-m foreclosure_scraper|merge_today_sources|resolver_backfill|load_board"],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


def _light_listing(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})

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


_LIGHT_FIELDS = tuple(set(_SIG_FIELDS) | {"city"})


def _collect_targets(docs: Path) -> tuple[list[tuple[str, object]], list[tuple[str, object]]]:
    """Board rows missing lat/lon, split into (key, Listing) pairs for the geocodable set
    (has a street address) and the centroid-only set (no address at all) -- WITHOUT
    load_board()'s full-board materialization (refused/OOM risk on this board's real size; see
    BOARD_LOAD_MAX_SOURCE_MB in web_artifact.py). Streams the published board read-only
    (board_stream.iter_board_rows()) and only ever builds a lightweight, unvalidated Listing
    (Listing.model_construct(), same trick resolver_backfill_parcel.py/run_dew_lien_enrichment.py
    use) for the rows that actually lack a coordinate -- the same pattern as those two scripts'
    2026-09-29 rewrites. `key` is each row's PRE-mutation dedupe_key(), captured before
    latitude/longitude are ever set, so the eventual patch lands on the exact row it was read
    from.
    """
    with_addr: list[tuple[str, object]] = []
    without_addr: list[tuple[str, object]] = []
    for rec in iter_board_rows(docs / "listings.json.gz"):
        lat, lon = rec.get("latitude"), rec.get("longitude")
        if lat and lon:
            continue
        li = _light_listing(rec)
        # city isn't in _SIG_FIELDS but build_address_string()/centroid_fallback() need it --
        # _light_listing() already pulled every _LIGHT_FIELDS key via model_construct below.
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
            continue
        if build_address_string(li):
            with_addr.append((key, li))
        else:
            without_addr.append((key, li))
    return with_addr, without_addr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="Cap total addresses processed (testing)")
    ap.add_argument("--skip-centroid-only", action="store_true",
                     help="Skip the no-address centroid-only pass (testing the Census tier alone)")
    args = ap.parse_args()

    if _engine_running():
        print("engine/backfill/another loader is running -- refusing to touch the board",
              file=sys.stderr)
        return 1

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="resolver_backfill_geocode")
    with lock:
        with_addr, without_addr = _collect_targets(docs)
        print(f"missing lat/lon: {len(with_addr) + len(without_addr):,} "
              f"({len(with_addr):,} geocodable, {len(without_addr):,} centroid-only)")

        if args.limit:
            with_addr = with_addr[: args.limit]
            print(f"--limit applied: processing {len(with_addr):,} addresses")

        geocoded = centroided = failed = 0
        pending_patches: dict[str, dict] = {}
        batches = [with_addr[i:i + BATCH_SIZE] for i in range(0, len(with_addr), BATCH_SIZE)]
        for bi, batch in enumerate(batches, 1):
            triples = [(key, li, build_address_string(li)) for key, li in batch]
            addresses = [addr for _, _, addr in triples]
            print(f"batch {bi}/{len(batches)}: {len(addresses)} addresses...", flush=True)
            results = geocode_batch_census(addresses)
            print(f"  matched: {len(results)}/{len(addresses)}", flush=True)

            for key, li, addr in triples:
                if addr in results:
                    lat, lon = results[addr]
                    pending_patches[key] = {"latitude": lat, "longitude": lon,
                                            "raw": {"geo_imprecise": "census_geocode"}}
                    geocoded += 1
                else:
                    c = centroid_fallback(li)
                    if c:
                        pending_patches[key] = {"latitude": c[0], "longitude": c[1],
                                                "raw": {"geo_imprecise": "county_centroid"}}
                        centroided += 1
                    else:
                        failed += 1

            if bi % CHECKPOINT_EVERY == 0 and not args.dry_run and pending_patches:
                stats = patch_existing_rows(
                    pending_patches, {"resolver_backfill_geocode_checkpoint": geocoded + centroided},
                    docs_dir=docs)
                print(f"  [checkpoint] patched {stats['applied']}/{len(pending_patches)} rows "
                      f"at batch {bi}/{len(batches)} "
                      f"({geocoded} geocoded, {centroided} centroided so far)", flush=True)
                pending_patches = {}

            if bi < len(batches):
                time.sleep(2)

        if not args.skip_centroid_only:
            for key, li in without_addr:
                c = centroid_fallback(li)
                if c:
                    pending_patches[key] = {"latitude": c[0], "longitude": c[1],
                                            "raw": {"geo_imprecise": "county_centroid_no_addr"}}
                    centroided += 1
                else:
                    failed += 1

        print(f"\n=== RESULTS ===")
        print(f"census geocoded: {geocoded:,}")
        print(f"centroid fallback: {centroided:,}")
        print(f"failed (no data): {failed:,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        if pending_patches:
            stats = patch_existing_rows(pending_patches, {"resolver_backfill_geocode": geocoded + centroided},
                                        docs_dir=docs)
            print(f"\npatched {stats['applied']}/{len(pending_patches)} rows "
                  f"(existing board: {stats['existing']:,})")
        else:
            print("\nnothing to patch this run")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
