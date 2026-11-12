#!/usr/bin/env python3
"""One-off backfill: correct ALREADY-PUBLISHED board rows written by
buncombe_unpaid_bills / buncombe_unpaid_bills_2024 (fixed 26dc41a3) and
nc_dam_safety (fixed 09cac01a) BEFORE those forward-only fixes landed.

WHY THIS EXISTS
    Both fixes correct what a FUTURE scrape will write. Neither touched the
    board: 26dc41a3's commit message says explicitly "the ~206+19 rows
    already published under the old behavior are still on the board
    unbackfilled"; 09cac01a's says "Backfilling the already-published bad
    nc_dam_safety/buncombe_unpaid_bills rows needs a separate board-write
    pass once the resolver lock is free." This is that pass.

    The bug in both cases: the scraper wrote the TAXPAYER'S/DAM OWNER'S
    MAILING address into street_address/city/zip_code instead of the
    property's real location. Verified live 2026-09-30 against the current
    board (docs/listings.json.gz, 219,530 rows): every currently-published
    row from these three sources still has the PRE-fix raw shape --
    raw['arcgis_distress'] has no 'house_num' key (the fixed scraper always
    queries it) and raw['state_contamination'] has neither 'NID_ID' nor
    'LATITUDE' (ditto) -- i.e. none of them have been re-scraped since the
    fix landed. Counts: buncombe_unpaid_bills 773, buncombe_unpaid_bills_2024
    79, nc_dam_safety 655.

HOW THE CORRECT ADDRESS IS FOUND
    Never re-derived from the bad data already on the board. Each affected
    row is re-matched against a FRESH live query of the exact same ArcGIS
    source the fixed scraper now reads, keyed by a stable identifier:
      * Buncombe: 'pin' (== the row's own parcel_id -- unaffected by the
        bug, so it's a safe join key). The live feature is run through the
        SAME arcgis_distress_layers._to_listing() the fixed scraper uses, so
        the corrected street_address/raw shape is byte-for-byte what a real
        re-scrape would have produced -- no parallel logic to drift.
      * nc_dam_safety: the old raw block has no NID_ID (that field wasn't
        even queried pre-fix), so the join key is (Dam_Name, County, Owner)
        -- confirmed live unique across all 917 in-footprint dams (5 pairs
        share a bare Dam_Name+County; all 917 are unique on the triple).
        The live feature is run through state_contamination._to_listing()
        the same way.

    Buncombe's fixed shape deliberately leaves city/zip_code unset (the
    layer has no genuine situs city/zip column, only the mailing one -- see
    26dc41a3). The existing lat/lon on these rows was therefore a Census
    geocode (or county-centroid fallback) of the WRONG address, and is
    cleared and recomputed here against the CORRECTED address, using the
    exact same free Census batch geocoder / county-centroid fallback
    scripts/resolver_backfill_geocode.py uses (imported, not reimplemented).
    Live-verified 2026-09-30: geocoding "<corrected street>, , NC " (blank
    city/zip, matching the fixed shape exactly) resolves cleanly -- e.g. "42
    DODE WHITAKER RD, , NC " -> (35.5314, -82.4093), ~100m from the
    OLD (wrong, neighboring-mailing-address-derived) coordinate on that same
    row, confirming the correction is real but subtle for non-absentee
    owners, and large for absentee ones (the whole point of the fix).
    nc_dam_safety's fixed shape carries no situs at all (a dam has no
    property address) -- LATITUDE/LONGITUDE/NID_ID come directly from the
    registry's own fields, no geocoding involved.

COLLISION GUARD (same pattern as scripts/backfill_tax_owed_amount_owed.py).
    Listing.dedupe_key() prefers parcel_id when set, so it is computed from
    each row's board-CURRENT identity fields (state/county/parcel_id/
    street_address/zip_code/case_number/source_url/listing_type) in ONE
    streaming pass that tallies every dedupe_key() on the WHOLE board, not
    just these three sources. Any key shared by more than one existing board
    row is dropped from patching entirely (reported, never guessed at) --
    this also structurally protects nc_dam_safety, where a pre-fix parcel_id
    was itself wrongly resolved off the bad mailing address by
    resolve_parcel_from_address.py (allowed to run on this source before
    09cac01a added it to DENY_SOURCES) and could in principle collide with
    an unrelated row.

BOARD I/O: board_stream.iter_board_rows() (read-only, no lazy-detail
sidecar) + web_artifact.patch_existing_rows() (task_0658b33b pattern) --
never load_board()/write_artifact() on this board size. Live ArcGIS queries
use http_client.client() with an asyncio.wait_for() hard wall-clock ceiling
on every attempt (the 02a67221 hardening: httpx's own timeout= only bounds
each read, not the whole request) and http_client.install_hard_sigint_kill()
so the process is always killable within a beat.

    python scripts/backfill_buncombe_dam_situs.py --dry-run
    scripts/with_board_lock.sh backfill_buncombe_dam_situs -- \\
        .venv/bin/python scripts/backfill_buncombe_dam_situs.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.http_client import client, install_hard_sigint_kill  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.scrapers.counties_generic import (  # noqa: E402
    arcgis_distress_layers as _adl,
)
from foreclosure_scraper.scrapers.counties_generic import (  # noqa: E402
    state_contamination as _sc,
)
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

from resolver_backfill_geocode import (  # noqa: E402
    build_address_string,
    centroid_fallback,
    geocode_batch_census,
)

#: Same identity fields web_artifact._APPEND_SIG_FIELDS keys patches on.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")

#: source string -> Layer.slug in arcgis_distress_layers.LAYERS
BUNCOMBE_SOURCES = {
    "counties_generic.arcgis_distress.buncombe_unpaid_bills": "buncombe_unpaid_bills",
    "counties_generic.arcgis_distress.buncombe_unpaid_bills_2024": "buncombe_unpaid_bills_2024",
}
DAM_SOURCE = "counties_generic.state_contamination.nc_dam_safety"

_LAYERS_BY_SLUG = {lay.slug: lay for lay in _adl.LAYERS}
_DAM_REGISTRY = next(r for r in _sc.REGISTRIES if r.slug == "nc_dam_safety")

_PIN_CHUNK = 100
_ARC_TIMEOUT_S = 30.0


def _dedupe_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def _buncombe_is_old_shape(raw: dict) -> bool:
    """True iff raw['arcgis_distress'] exists but predates the fix (no house_num --
    the fixed scraper always queries it, so its absence means this row's raw block
    was captured before 26dc41a3)."""
    ag = raw.get("arcgis_distress")
    return isinstance(ag, dict) and bool(ag) and "house_num" not in ag


def _dam_is_old_shape(raw: dict) -> bool:
    """True iff raw['state_contamination'] exists but predates the fix (neither
    NID_ID nor LATITUDE -- the fixed scraper always queries both)."""
    sc = raw.get("state_contamination")
    return (isinstance(sc, dict) and bool(sc)
            and "NID_ID" not in sc and "LATITUDE" not in sc)


def _collect_targets(docs: Path):
    """ONE streaming pass over the whole board: tally every row's dedupe_key()
    (collision guard, see module docstring) and collect candidates from the 3
    affected sources that still show the pre-fix raw shape.

    Returns (scanned, key_counts, buncombe_candidates, dam_candidates) where
    buncombe_candidates is [(key, slug, pin), ...] and dam_candidates is
    [(key, dam_name, county, owner), ...].
    """
    key_counts: Counter = Counter()
    buncombe_candidates: list[tuple[str, str, str]] = []
    dam_candidates: list[tuple[str, str, str, str | None]] = []
    scanned = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        scanned += 1
        key = _dedupe_key(rec)
        if key is None:
            continue
        key_counts[key] += 1
        src = rec.get("source")
        raw = rec.get("raw") or {}
        if src in BUNCOMBE_SOURCES and _buncombe_is_old_shape(raw):
            ag = raw.get("arcgis_distress") or {}
            pin = ag.get("pin") or rec.get("parcel_id")
            if pin:
                buncombe_candidates.append((key, BUNCOMBE_SOURCES[src], str(pin)))
        elif src == DAM_SOURCE and _dam_is_old_shape(raw):
            sc = raw.get("state_contamination") or {}
            name = sc.get("Dam_Name")
            county = rec.get("county")
            owner = sc.get("Owner")
            if name and county:
                dam_candidates.append((key, str(name), str(county), owner))
    return scanned, key_counts, buncombe_candidates, dam_candidates


async def _fetch_buncombe_by_pin(slug: str, pins: set[str]) -> dict[str, dict]:
    """Live-query the named Buncombe FeatureServer for exactly `pins`, chunked.
    Returns {pin: attributes}. Mockable in tests (see tests/test_backfill_
    buncombe_dam_situs.py) -- this is the only function that touches the network
    for Buncombe."""
    lay = _LAYERS_BY_SLUG[slug]
    out: dict[str, dict] = {}
    ordered = sorted(pins)
    async with client() as c:
        for i in range(0, len(ordered), _PIN_CHUNK):
            chunk = ordered[i:i + _PIN_CHUNK]
            where = "pin IN (" + ",".join("'" + p.replace("'", "''") + "'" for p in chunk) + ")"
            # POST, not GET: a 100-pin IN-clause runs ~2-3KB, well past this host's
            # (IIS-fronted) URL-length limit -- confirmed live 2026-09-30, a GET with
            # the same where= 404s (generic IIS "file not found", not a WAF/auth
            # wall) while the identical filter as a POST body returns 200 cleanly.
            # Same public /query endpoint, same filter, just a different HTTP verb.
            r = await asyncio.wait_for(
                c.post(lay.url + "/query", data={
                    "where": where,
                    "outFields": ",".join(lay.fields),
                    "returnGeometry": "false",
                    "resultRecordCount": _PIN_CHUNK,
                    "f": "json",
                }, timeout=_ARC_TIMEOUT_S),
                timeout=_ARC_TIMEOUT_S,
            )
            if r.status_code != 200:
                raise RuntimeError(f"{slug}: HTTP {r.status_code}")
            d = r.json()
            if "error" in d:
                raise RuntimeError(f"{slug}: {str(d['error'])[:200]}")
            for f in d.get("features") or []:
                a = f.get("attributes") or {}
                p = a.get("pin")
                if p:
                    out[str(p)] = a
    return out


async def _fetch_dam_registry() -> list[dict]:
    """Live-query the full in-footprint nc_dam_safety registry (~917 rows, one
    page) using the SAME Registry.where/.fields/.url the fixed scraper reads.
    Mockable in tests -- the only function that touches the network for dams."""
    reg = _DAM_REGISTRY
    out: list[dict] = []
    offset = 0
    async with client() as c:
        while True:
            r = await asyncio.wait_for(
                c.post(reg.url, data={
                    "where": reg.where, "outFields": ",".join(reg.fields),
                    "returnGeometry": "false", "resultOffset": offset,
                    "resultRecordCount": 1000, "orderByFields": reg.fields[0],
                    "f": "json",
                }, timeout=90.0),
                timeout=90.0,
            )
            if r.status_code != 200:
                raise RuntimeError(f"nc_dam_safety: HTTP {r.status_code}")
            d = r.json()
            if "error" in d:
                raise RuntimeError(f"nc_dam_safety: {str(d['error'])[:200]}")
            feats = d.get("features") or []
            out.extend(f.get("attributes") or {} for f in feats)
            if len(feats) < 1000 or not d.get("exceededTransferLimit"):
                break
            offset += 1000
    return out


def _norm(s) -> str:
    return str(s or "").strip().upper()


def _build_dam_index(live_rows: list[dict]):
    """(by_triple, by_pair): by_triple keys on the confirmed-unique (Dam_Name,
    County, Owner); by_pair is the fallback for a board row whose captured Owner
    string doesn't match exactly (formatting drift) but whose (Dam_Name, County)
    is itself unique among live rows."""
    by_triple: dict[tuple[str, str, str], dict] = {}
    by_pair: dict[tuple[str, str], list[dict]] = {}
    for a in live_rows:
        name = _norm(a.get("Dam_Name"))
        county = _norm(_sc._county_of(str(a.get("COUNTY") or "")) or "")
        owner = _norm(a.get("Owner"))
        by_triple[(name, county, owner)] = a
        by_pair.setdefault((name, county), []).append(a)
    return by_triple, by_pair


def _dam_lookup(index, name: str, county: str, owner: str | None) -> dict | None:
    by_triple, by_pair = index
    name_n = _norm(name)
    county_n = _norm(_sc._county_of(county) or county)
    owner_n = _norm(owner)
    a = by_triple.get((name_n, county_n, owner_n))
    if a is not None:
        return a
    pair = by_pair.get((name_n, county_n))
    if pair and len(pair) == 1:
        return pair[0]
    return None  # not found, or ambiguous (>1 live dam) -- never guess


def main() -> int:
    # See http_client.install_hard_sigint_kill's docstring / the 02a67221 fix:
    # a hung ArcGIS connection can otherwise survive Ctrl-C.
    install_hard_sigint_kill(reason="backfill_buncombe_dam_situs")

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap candidates PER SOURCE GROUP (testing)")
    ap.add_argument("--skip-geocode", action="store_true",
                    help="Leave corrected Buncombe rows with lat/lon cleared "
                         "instead of re-geocoding (testing / offline)")
    args = ap.parse_args()

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="backfill_buncombe_dam_situs")

    with lock:
        scanned, key_counts, buncombe_cands, dam_cands = _collect_targets(docs)
        print(f"scanned {scanned:,} board rows")
        print(f"buncombe candidates (pre-fix shape): {len(buncombe_cands):,}")
        print(f"dam candidates (pre-fix shape): {len(dam_cands):,}")

        if args.limit:
            buncombe_cands = buncombe_cands[:args.limit]
            dam_cands = dam_cands[:args.limit]

        stats: Counter = Counter()

        def _collision_ok(key: str) -> bool:
            if key_counts[key] > 1:
                stats["skipped_key_collision"] += 1
                return False
            return True

        buncombe_cands = [c for c in buncombe_cands if _collision_ok(c[0])]
        dam_cands = [c for c in dam_cands if _collision_ok(c[0])]

        # --- live-fetch Buncombe, grouped by which FeatureServer table ---
        pins_by_slug: dict[str, set[str]] = {}
        for _key, slug, pin in buncombe_cands:
            pins_by_slug.setdefault(slug, set()).add(pin)
        live_by_slug: dict[str, dict[str, dict]] = {}
        for slug, pins in pins_by_slug.items():
            live_by_slug[slug] = asyncio.run(_fetch_buncombe_by_pin(slug, pins))
            print(f"  live-fetched {len(live_by_slug[slug]):,}/{len(pins):,} "
                  f"pins for {slug}")

        # --- live-fetch the dam registry once ---
        dam_index = ({}, {})
        if dam_cands:
            dam_live = asyncio.run(_fetch_dam_registry())
            dam_index = _build_dam_index(dam_live)
            print(f"  live-fetched {len(dam_live):,} in-footprint dam rows "
                  f"({len(dam_index[0]):,} unique name+county+owner)")

        # --- build corrected Buncombe listings, then batch-geocode them ---
        buncombe_new: dict[str, Listing] = {}
        for key, slug, pin in buncombe_cands:
            attrs = live_by_slug.get(slug, {}).get(pin)
            if not attrs:
                stats["buncombe_not_found_live"] += 1
                continue
            new_li = _adl._to_listing(attrs, _LAYERS_BY_SLUG[slug])
            if new_li is None or not new_li.street_address:
                stats["buncombe_live_no_situs"] += 1
                continue
            buncombe_new[key] = new_li
            stats["buncombe_matched"] += 1

        addr_by_key = {k: build_address_string(li) for k, li in buncombe_new.items()}
        geocode_results: dict[str, tuple[float, float]] = {}
        if not args.skip_geocode:
            uniq_addrs = sorted({a for a in addr_by_key.values() if a})
            CH = 900
            for i in range(0, len(uniq_addrs), CH):
                geocode_results.update(geocode_batch_census(uniq_addrs[i:i + CH]))

        patches: dict[str, dict] = {}
        for key, li in buncombe_new.items():
            addr_s = addr_by_key.get(key)
            coord = geocode_results.get(addr_s) if addr_s else None
            if coord is not None:
                stats["buncombe_census_geocoded"] += 1
            else:
                coord = centroid_fallback(li)
                if coord is not None:
                    stats["buncombe_centroid_fallback"] += 1
                else:
                    stats["buncombe_no_coordinate"] += 1
            lat, lon = coord if coord else (None, None)
            raw_patch = {"arcgis_distress": li.raw["arcgis_distress"]}
            if "owner_mailing" in li.raw:
                raw_patch["owner_mailing"] = li.raw["owner_mailing"]
            patches[key] = {
                "street_address": li.street_address,
                "city": li.city,
                "zip_code": li.zip_code,
                "latitude": lat,
                "longitude": lon,
                "description": li.description,
                "raw": raw_patch,
            }

        # --- build corrected dam listings ---
        for key, name, county, owner in dam_cands:
            attrs = _dam_lookup(dam_index, name, county, owner)
            if attrs is None:
                stats["dam_not_found_live_or_ambiguous"] += 1
                continue
            new_li = _sc._to_listing(attrs, _DAM_REGISTRY)
            if new_li is None:
                stats["dam_live_no_data"] += 1
                continue
            stats["dam_matched"] += 1
            patches[key] = {
                "street_address": new_li.street_address,
                "city": new_li.city,
                "zip_code": new_li.zip_code,
                "latitude": new_li.latitude,
                "longitude": new_li.longitude,
                "parcel_id": new_li.parcel_id,
                "description": new_li.description,
                "raw": {"state_contamination": new_li.raw["state_contamination"]},
            }

        print("\n=== match/geocode stats ===")
        for k, v in sorted(stats.items()):
            print(f"  {v:7,d}  {k}")
        print(f"\ntotal patches ready: {len(patches):,}")

        if args.dry_run:
            print("\nDRY RUN — nothing written.")
            return 0

        result = patch_existing_rows(
            patches, {"backfill_buncombe_dam_situs": f"{len(patches)} rows"},
            docs_dir=docs)
        print("\n=== patch_existing_rows result ===")
        for k, v in result.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
