#!/usr/bin/env python3
"""One-off backfill: apply the Gaston NC sqft/year_built/value GIS fix (eb8af822,
2026-09-30) to board rows that were already published BEFORE that fix landed.

WHY THIS EXISTS
    eb8af822 added an explicit `out_fields` to enrichment_owner_mailing.py's
    COUNTY_GIS["NC:Gaston"] spec (PublicGIS/Parcels/FeatureServer/11), requesting
    SQFT/YEARBLT/TOTVAL for the first time, and taught _SPEC_PATTERNS the bare
    "SQFT"/"YEARBLT" Esri-CAMA column names this layer uses. That fix corrects
    what a FUTURE owner_mailing enrichment pass will write; it does not touch
    rows the pre-fix code already resolved -- those rows have owner/mailing
    filled (that part worked) but living_sqft/year_built/tax_value/market_value/
    assessed_value still blank, because the pre-fix query never even asked the
    layer for those columns. This script is the backfill pass for those rows.

    Deliberately NOT run the day the fix landed (2026-09-30): multiple sessions
    were active under heavy memory pressure (swap 78-90%+) and a kernel panic
    had happened earlier that week from stacking board writes with concurrent
    agent work. Run the next morning once conditions were verified safer (one
    other session, swap ~63%).

SCOPE (bounded, not a full-board pass)
    Only NC:Gaston rows currently missing at least one of living_sqft /
    year_built / {tax_value, market_value, assessed_value}, AND that carry a
    parcel_id (board field, or raw.owner_mailing.parcel_id as a fallback) --
    found by one streaming pass over the whole board (scripts/board_stream.py),
    with the same whole-board dedupe_key() collision guard
    backfill_buncombe_dam_situs.py uses (a key shared by >1 existing row is
    dropped from patching entirely, never guessed at).

    Gaston rows with NO parcel_id at all are reported but left unpatched --
    matching them would need the heavier per-row situs/street scan
    (enrichment_owner_mailing._match_attrs's fallback path), which is a
    meaningfully different cost profile (one scan query per row, up to
    _SITUS_SCAN_CAP rows paged) and is out of scope for this bounded pass.

    A row whose live GIS record genuinely has no SQFT/YEARBLT (true vacant
    land -- eb8af822's own live verification found ~22% of all Gaston parcels
    carry SQFT<=0) is correctly left unpatched for that field: _extract_specs()
    only extracts a value that passes its own sanity check, exactly the same
    rule production enrichment uses, so "no new data" is a legitimate, expected
    outcome for some candidates, not a bug.

HOW THE LIVE DATA IS FOUND
    Bulk IN-clause POST queries (same pattern as backfill_buncombe_dam_situs.py's
    _fetch_buncombe_by_pin), chunked at 100 PINs/request, against the EXACT same
    URL + out_fields enrichment_owner_mailing.COUNTY_GIS["NC:Gaston"] now carries
    (single source of truth -- nothing here duplicates the fixed field list).
    Each candidate's stored parcel_id is queried both as-is and in its
    punctuation-stripped form (Gaston PINs can appear dashed or bare across
    sources), since an IN-clause needs an exact string match unlike the LIKE
    matching enrichment_owner_mailing.py's per-lead resolve path uses.
    _extract_specs()/_extract_value() (imported, not reimplemented) parse the
    returned attributes exactly the way production enrichment does.

BOARD I/O: board_stream.iter_board_rows() (read-only streaming scan) +
web_artifact.patch_existing_rows() (task_0658b33b pattern) -- never
load_board()/write_artifact() on this board size (2.4+ GB). The existing
board is over BOARD_PATCH_MAX_SOURCE_MB (2,300 MB); run with
BOARD_PATCH_ALLOW_LARGE=1, supervised, with an external RSS + physical-
footprint watchdog (see docs/HANDOFF.md / web_artifact.py's own comments on
why RSS alone is not sufficient and a hard SIGKILL backstop is required).

    .venv/bin/python scripts/backfill_gaston_sqft_valtot.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python scripts/backfill_gaston_sqft_valtot.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_owner_mailing import (  # noqa: E402
    COUNTY_GIS, _extract_specs, _extract_value,
)
from foreclosure_scraper.http_client import client, install_hard_sigint_kill  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

#: Same identity fields web_artifact._APPEND_SIG_FIELDS keys patches on.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")

_SPEC = COUNTY_GIS["NC:Gaston"]
_PIN_FIELD = _SPEC["parcel"]  # "PIN"
_PIN_CHUNK = 100
_ARC_TIMEOUT_S = 30.0
_VALUE_FIELDS = ("tax_value", "market_value", "assessed_value")


def _dedupe_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def _strip_pid(pid: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", pid or "").upper()


def _is_missing(val) -> bool:
    return not (isinstance(val, (int, float)) and val > 0)


def _row_missing_target(rec: dict) -> bool:
    return (_is_missing(rec.get("living_sqft"))
            or _is_missing(rec.get("year_built"))
            or all(_is_missing(rec.get(f)) for f in _VALUE_FIELDS))


def _row_parcel_id(rec: dict) -> str | None:
    pid = rec.get("parcel_id")
    if pid:
        return str(pid)
    om = (rec.get("raw") or {}).get("owner_mailing")
    if isinstance(om, dict) and om.get("parcel_id"):
        return str(om["parcel_id"])
    return None


def _collect_targets(docs: Path):
    """ONE streaming pass over the whole board: tally every row's dedupe_key()
    (collision guard) and collect Gaston NC candidates missing sqft/year_built/
    value that carry a parcel_id, along with their CURRENT field values (so the
    patch step only fills what is still actually missing).

    Returns (scanned, gaston_total, no_parcel, key_counts, candidates) where
    candidates is [(key, parcel_id, current_values_dict), ...].
    """
    key_counts: Counter = Counter()
    candidates: list[tuple[str, str, dict]] = []
    scanned = gaston_total = no_parcel = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        scanned += 1
        key = _dedupe_key(rec)
        if key is None:
            continue
        key_counts[key] += 1
        if rec.get("state") != "NC":
            continue
        if (rec.get("county") or "").strip().title() != "Gaston":
            continue
        gaston_total += 1
        if not _row_missing_target(rec):
            continue
        pid = _row_parcel_id(rec)
        if not pid:
            no_parcel += 1
            continue
        cur = {f: rec.get(f) for f in ("living_sqft", "year_built", *_VALUE_FIELDS)}
        candidates.append((key, pid, cur))
    return scanned, gaston_total, no_parcel, key_counts, candidates


async def _fetch_gaston_by_pins(pins: set[str]) -> dict[str, dict]:
    """Live-query Gaston's PublicGIS/Parcels/FeatureServer/11 for exactly `pins`
    (chunked IN-clause POST, same host/url/out_fields the fixed owner_mailing
    spec uses). Returns {PIN-as-returned-by-the-server: attributes}."""
    out: dict[str, dict] = {}
    ordered = sorted(pins)
    async with client(timeout=_ARC_TIMEOUT_S) as c:
        for i in range(0, len(ordered), _PIN_CHUNK):
            chunk = ordered[i:i + _PIN_CHUNK]
            where = f"{_PIN_FIELD} IN (" + ",".join(
                "'" + p.replace("'", "''") + "'" for p in chunk) + ")"
            r = await asyncio.wait_for(
                c.post(_SPEC["url"] + "/query", data={
                    "where": where,
                    "outFields": _SPEC["out_fields"],
                    "returnGeometry": "false",
                    "resultRecordCount": _PIN_CHUNK,
                    "f": "json",
                }, timeout=_ARC_TIMEOUT_S),
                timeout=_ARC_TIMEOUT_S,
            )
            if r.status_code != 200:
                raise RuntimeError(f"Gaston GIS: HTTP {r.status_code}")
            d = r.json()
            if "error" in d:
                raise RuntimeError(f"Gaston GIS: {str(d['error'])[:200]}")
            for f in d.get("features") or []:
                a = f.get("attributes") or {}
                p = a.get(_PIN_FIELD)
                if p:
                    out[str(p)] = a
    return out


def main() -> int:
    # See http_client.install_hard_sigint_kill's docstring: a hung ArcGIS
    # connection can otherwise survive Ctrl-C.
    install_hard_sigint_kill(reason="backfill_gaston_sqft_valtot")

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap candidates (testing)")
    args = ap.parse_args()

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="backfill_gaston_sqft_valtot")

    with lock:
        print(f"[{time.strftime('%H:%M:%S')}] scanning board for Gaston NC "
              f"gap rows...", flush=True)
        scanned, gaston_total, no_parcel, key_counts, candidates = _collect_targets(docs)
        print(f"scanned {scanned:,} board rows")
        print(f"Gaston NC rows: {gaston_total:,}")
        print(f"  candidates (missing sqft/year/value, have a parcel_id): "
              f"{len(candidates):,}")
        print(f"  missing but NO parcel_id (out of scope this pass): {no_parcel:,}")

        if args.limit:
            candidates = candidates[:args.limit]

        stats: Counter = Counter()
        deduped: list[tuple[str, str, dict]] = []
        for key, pid, cur in candidates:
            if key_counts[key] > 1:
                stats["skipped_key_collision"] += 1
                continue
            deduped.append((key, pid, cur))
        candidates = deduped

        # query set: raw parcel_id as stored on the board, plus its
        # punctuation-stripped form (an IN-clause needs an exact string match,
        # unlike enrichment_owner_mailing.py's per-lead LIKE matching).
        pins_to_query: set[str] = set()
        for _key, pid, _cur in candidates:
            pins_to_query.add(pid)
            pins_to_query.add(_strip_pid(pid))
        pins_to_query.discard("")

        print(f"[{time.strftime('%H:%M:%S')}] live-querying {len(pins_to_query):,} "
              f"PIN variants for {len(candidates):,} candidates...", flush=True)
        t0 = time.time()
        live = asyncio.run(_fetch_gaston_by_pins(pins_to_query))
        print(f"  live-matched {len(live):,} distinct PIN strings in "
              f"{int(time.time() - t0)}s", flush=True)

        live_by_stripped: dict[str, dict] = {}
        for p, a in live.items():
            live_by_stripped.setdefault(_strip_pid(p), a)

        now_iso = datetime.now(timezone.utc).isoformat()
        patches: dict[str, dict] = {}
        for key, pid, cur in candidates:
            attrs = live.get(pid) or live.get(_strip_pid(pid)) or live_by_stripped.get(_strip_pid(pid))
            if attrs is None:
                stats["not_found_live"] += 1
                continue
            specs = _extract_specs(attrs)
            val = _extract_value(attrs)
            patch: dict = {}
            if specs.get("living_sqft") and _is_missing(cur.get("living_sqft")):
                patch["living_sqft"] = specs["living_sqft"]
            if specs.get("year_built") and _is_missing(cur.get("year_built")):
                patch["year_built"] = int(specs["year_built"])
            if val:
                for f in _VALUE_FIELDS:
                    if _is_missing(cur.get(f)):
                        patch[f] = val
            if not patch:
                # Genuinely no new data (e.g. true vacant land, SQFT<=0 live too) --
                # a legitimate outcome, not a failure. See module docstring.
                stats["live_no_new_data"] += 1
                continue
            patch["raw"] = {"gaston_sqft_backfill": {
                "ts": now_iso, "pin_queried": pid,
                "pin_live": attrs.get(_PIN_FIELD),
                "living_sqft": specs.get("living_sqft"),
                "year_built": specs.get("year_built"),
                "value": val,
            }}
            patches[key] = patch
            stats["matched"] += 1

        print("\n=== match stats ===")
        for k, v in sorted(stats.items()):
            print(f"  {v:7,d}  {k}")
        print(f"\ntotal patches ready: {len(patches):,}")

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
            return 0

        result = patch_existing_rows(
            patches, {"backfill_gaston_sqft_valtot": f"{len(patches)} rows"},
            docs_dir=docs)
        print("\n=== patch_existing_rows result ===")
        for k, v in result.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
