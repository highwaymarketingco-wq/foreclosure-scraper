#!/usr/bin/env python3
"""One-off backfill: apply the Anderson SC situs+value GIS fix (commits 55f6d2a1
and ce25bd3a, 2026-09-30) to board rows that were already published BEFORE that
fix landed.

WHY THIS EXISTS
    55f6d2a1 added `enrichment_arcgis.SC_GIS["Anderson"]` (situs+value only --
    owner is confirmed permanently null server-side on this county's live GIS).
    ce25bd3a fixed `enrichment_owner_mailing.COUNTY_GIS["SC:Anderson"]`, whose
    field names (OWNER/OWNER_ADDR/CITY/ZIPCODE) had drifted off the live schema
    since 2026-08-03 -- ArcGIS silently drops an unknown outFields name instead
    of erroring, so the spec always got owner="" and mailing="", which tripped
    `_build_result`'s old "no owner and no mailing -> discard" gate and threw
    away every real PHYS_ADDR (situs) / MRKT_VALUE (value) hit the layer
    actually had. That gate is now widened to accept a situs-only or
    value-only match. Both fixes point at the SAME live ArcGIS layer
    (gis.cityofandersonsc.com/.../WaterUtilities/County_Parcels/FeatureServer/0,
    TMS-keyed, fields TMS/PHYS_ADDR/MRKT_VALUE/SALE_PRICE/SALE_YEAR/DBOOK/DPAGE/
    TAXOWNSTR -- TAXOWNSTR is always-null and deliberately not used as owner).

    Neither fix touches rows already published before today: those rows'
    street_address/tax_value/market_value/assessed_value were filled (or left
    blank) by the PRE-fix code, which either never requested these fields at
    all (pre-55f6d2a1: enrichment_gis_attrs had no SC_GIS entry for Anderson to
    resolve against) or requested them, got a real hit, and then silently
    discarded it at the gate (pre-ce25bd3a, for enrichment_owner_mailing's own
    tax_value/market_value/assessed_value fill, which never runs through this
    script -- see SCOPE below). This script is the backfill pass for the rows
    that are still missing what the fix would now give them.

    Deliberately WRITE + DRY-RUN VALIDATE ONLY this session. Per the same
    memory-safety protocol backfill_gaston_sqft_valtot.py (166a11ad) used: this
    is a separate, later, supervised task. `patch_existing_rows()` is never
    called for real here -- `--dry-run` is the only mode this script runs in
    until that follow-up session.

SCOPE (bounded, not a full-board pass, and not a re-run of the full enrichment
pipeline)
    Only Anderson, SC rows currently missing `street_address` (the board's
    primary situs-address field) and/or missing ALL THREE of tax_value /
    market_value / assessed_value, AND that carry a parcel_id (TMS) -- found by
    one streaming pass over the whole board (board_stream.iter_board_rows),
    with the same whole-board dedupe_key() collision guard
    backfill_gaston_sqft_valtot.py / backfill_buncombe_dam_situs.py use (a key
    shared by >1 existing row is dropped from patching entirely, never guessed
    at).

    Anderson rows with NO parcel_id at all are reported but left unpatched --
    matching them would need the heavier per-row situs/street scan
    (enrichment_owner_mailing._match_attrs's fallback path), a different cost
    profile, out of scope for this bounded pass (same call Gaston made).

    FIELD CHOICE, disclosed: the two fix commits are about two different
    enrichment modules that never run against each other's output --
    enrichment_owner_mailing.enrich_owner_mailing() (ce25bd3a) fills
    tax_value/market_value/assessed_value but ONLY ever stashes situs in
    raw.owner_mailing.situs, never in the board's first-class street_address
    field; enrichment_gis_attrs.apply_gis_attrs() (the consumer of 55f6d2a1's
    SC_GIS entry) is the module that actually promotes a GIS situs field into
    street_address, via point-in-polygon/parcel lookup against the same
    SC_GIS/COUNTY_GIS-equivalent spec. Both point at the identical Anderson
    ArcGIS layer and the identical PHYS_ADDR / MRKT_VALUE columns. Rather than
    re-running two separate enrichment passes against the exact same live
    layer for the exact same two columns, this script does ONE bulk TMS query
    against COUNTY_GIS["SC:Anderson"] (the single already-fixed source of
    truth for this layer's url/out_fields/parcel field) and fills BOTH
    first-class targets from it:
      - street_address <- situs, extracted via the real, unmodified
        enrichment_owner_mailing._join(attrs, spec["situs"]) (NOT reimplemented),
        then given the same presentation-level cleanup
        enrichment_gis_attrs.apply_gis_attrs uses for this exact field
        (collapse internal whitespace, reject blank / too-short / PO-box
        strings) since that is the actual bar production code applies before
        writing into street_address -- PHYS_ADDR carries the subdivision name
        as a prefix (e.g. "SPRINGSIDE        300 SPRINGSIDE CIR") and that
        prefix is cosmetic, not reimplemented extraction logic.
      - tax_value / market_value / assessed_value (whichever are still
        missing) <- enrichment_owner_mailing._extract_value(attrs), the exact
        function ce25bd3a's gate fix was written to unlock, reused unmodified
        (same call backfill_gaston_sqft_valtot.py made for Gaston's value
        fields).
    TAXOWNSTR (owner) is read but never used -- confirmed permanently null,
    per both commits' live verification; writing it here would always be a
    no-op and risks someone mistaking this script for an owner backfill.

LESSON APPLIED (from backfill_gaston_sqft_valtot.py / commit ee51eb4d): that
    script's dry-run reported "5,075 patches ready" but the real run patched
    only 102 -- the dry-run's headline number was not cross-checked against the
    real eligibility breakdown before being reported. This script prints, and
    this session's report relies on, the FULL breakdown at every stage (board
    candidates -> has-parcel_id -> live-matched -> each field's OWN missing/
    would-fill counts, not just a single combined "matched" tally) specifically
    so an inflated headline number cannot slip through unexamined. It also
    independently re-derives each patch's field set from `cur` (the value
    captured during the SAME streaming pass the eligibility counts come from,
    not a second read) so the reported per-field breakdown and the dry-run's
    `patches` dict can never silently diverge.

HOW THE LIVE DATA IS FOUND
    Bulk IN-clause POST queries (same pattern as backfill_gaston_sqft_valtot.py
    / backfill_buncombe_dam_situs.py's _fetch_*_by_pin), chunked at 100 TMS/
    request, against the EXACT same URL + out_fields
    enrichment_owner_mailing.COUNTY_GIS["SC:Anderson"] now carries (single
    source of truth -- nothing here duplicates the fixed field list). Each
    candidate's stored parcel_id is queried both as-is and in its
    punctuation-stripped form (an IN-clause needs an exact string match,
    unlike enrichment_owner_mailing.py's per-lead LIKE matching).

BOARD I/O: board_stream.iter_board_rows() (read-only streaming scan) +
web_artifact.patch_existing_rows() (not called for real this session) --
never load_board()/write_artifact() on this board size.

    .venv/bin/python scripts/backfill_anderson_situs_value.py --dry-run
    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python scripts/backfill_anderson_situs_value.py   # NOT run this session

DRY-RUN FINDING, 2026-10-01 (why the collision-guard count is so large -- do not
mistake this for a bug if it's re-run and looks the same): of 869 raw
candidates, 819 were dropped by the dedupe_key() collision guard, but that is
NOT 819 independent properties being conservatively skipped -- it is 4 distinct
parcels, one of which alone (TMS 1233003020) accounts for 790 separate board
rows (bankruptcy, lis_pendens, tax_sale, probate_notice, and landandfarm
listings for what is almost certainly one repeatedly-litigated property, never
merged across sources). The other 3 colliding parcels account for 16, 10 and 3
rows respectively. This is a pre-existing, unrelated board dedupe gap -- out of
scope for this script, which correctly refuses to guess which (if any) of a
colliding parcel's many rows should receive the patch. The real, uniquely-
identified eligible pool this pass acts on is 50 rows, not 869.
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
    COUNTY_GIS, _extract_value, _join,
)
from foreclosure_scraper.http_client import client, install_hard_sigint_kill  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, patch_existing_rows  # noqa: E402

#: Same identity fields web_artifact._APPEND_SIG_FIELDS keys patches on.
_SIG_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
              "case_number", "source_url", "listing_type")

_SPEC = COUNTY_GIS["SC:Anderson"]
_PIN_FIELD = _SPEC["parcel"]  # "TMS"
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


def _is_missing_value(val) -> bool:
    return not (isinstance(val, (int, float)) and val > 0)


def _is_missing_addr(val) -> bool:
    return not (isinstance(val, str) and val.strip())


def _clean_situs(raw_situs: str) -> str | None:
    """Presentation-level cleanup matching enrichment_gis_attrs.apply_gis_attrs's
    own bar for writing a GIS situs string into street_address: collapse
    internal whitespace, reject blank / too-short / PO-box strings. This is
    NOT the extraction (that is _join(attrs, spec['situs']), reused verbatim
    above) -- just the same cosmetic gate production code already applies."""
    s = re.sub(r"\s+", " ", (raw_situs or "")).strip()
    if not s or len(s) < 5 or s.upper().startswith("P.O."):
        return None
    return s


def _row_missing_target(rec: dict) -> bool:
    return (_is_missing_addr(rec.get("street_address"))
            or all(_is_missing_value(rec.get(f)) for f in _VALUE_FIELDS))


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
    (collision guard) and collect Anderson SC candidates missing street_address
    and/or value that carry a parcel_id, along with their CURRENT field values
    (so the patch step only fills what is still actually missing, and the
    reported breakdown comes from this same snapshot -- never a second read).

    Returns (scanned, anderson_total, no_parcel, key_counts, candidates) where
    candidates is [(key, parcel_id, current_values_dict), ...].
    """
    key_counts: Counter = Counter()
    candidates: list[tuple[str, str, dict]] = []
    scanned = anderson_total = no_parcel = 0
    for rec in iter_board_rows(docs / "listings.json.gz"):
        scanned += 1
        key = _dedupe_key(rec)
        if key is None:
            continue
        key_counts[key] += 1
        if rec.get("state") != "SC":
            continue
        if (rec.get("county") or "").strip().title() != "Anderson":
            continue
        anderson_total += 1
        if not _row_missing_target(rec):
            continue
        pid = _row_parcel_id(rec)
        if not pid:
            no_parcel += 1
            continue
        cur = {f: rec.get(f) for f in ("street_address", *_VALUE_FIELDS)}
        candidates.append((key, pid, cur))
    return scanned, anderson_total, no_parcel, key_counts, candidates


async def _fetch_anderson_by_tms(pins: set[str]) -> dict[str, dict]:
    """Live-query Anderson's County_Parcels/FeatureServer/0 for exactly `pins`
    (chunked IN-clause POST, same host/url/out_fields the fixed owner_mailing
    spec uses). Returns {TMS-as-returned-by-the-server: attributes}."""
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
                raise RuntimeError(f"Anderson GIS: HTTP {r.status_code}")
            d = r.json()
            if "error" in d:
                raise RuntimeError(f"Anderson GIS: {str(d['error'])[:200]}")
            for f in d.get("features") or []:
                a = f.get("attributes") or {}
                p = a.get(_PIN_FIELD)
                if p:
                    out[str(p)] = a
    return out


def main() -> int:
    # See http_client.install_hard_sigint_kill's docstring: a hung ArcGIS
    # connection can otherwise survive Ctrl-C.
    install_hard_sigint_kill(reason="backfill_anderson_situs_value")

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap candidates (testing)")
    args = ap.parse_args()

    docs = REPO / "docs"
    lock = contextlib.nullcontext() if args.dry_run else board_lock(
        REPO, owner="backfill_anderson_situs_value")

    with lock:
        print(f"[{time.strftime('%H:%M:%S')}] scanning board for Anderson SC "
              f"gap rows...", flush=True)
        scanned, anderson_total, no_parcel, key_counts, candidates = _collect_targets(docs)
        print(f"scanned {scanned:,} board rows")
        print(f"Anderson SC rows: {anderson_total:,}")
        print(f"  candidates (missing street_address and/or value, have a "
              f"parcel_id): {len(candidates):,}")
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
        print(f"  after dedupe_key() collision guard: {len(candidates):,} "
              f"eligible candidates "
              f"({stats['skipped_key_collision']:,} dropped as key collisions)")

        # Pre-live eligibility breakdown, from the SAME `cur` snapshot the
        # streaming pass captured -- computed BEFORE any live query, so it
        # cannot be contaminated by anything the live call returns.
        pre_missing_addr = sum(1 for _k, _p, cur in candidates if _is_missing_addr(cur.get("street_address")))
        pre_missing_value = sum(1 for _k, _p, cur in candidates
                                if all(_is_missing_value(cur.get(f)) for f in _VALUE_FIELDS))
        pre_missing_both = sum(1 for _k, _p, cur in candidates
                               if _is_missing_addr(cur.get("street_address"))
                               and all(_is_missing_value(cur.get(f)) for f in _VALUE_FIELDS))
        print(f"\n=== pre-live eligibility (from the board snapshot itself) ===")
        print(f"  missing street_address:                  {pre_missing_addr:,}")
        print(f"  missing ALL of tax/market/assessed value: {pre_missing_value:,}")
        print(f"  missing BOTH:                             {pre_missing_both:,}")
        print(f"  (these three should partition {len(candidates):,} candidates "
              f"as addr-only + value-only + both = "
              f"{pre_missing_addr - pre_missing_both:,} + "
              f"{pre_missing_value - pre_missing_both:,} + {pre_missing_both:,} "
              f"= {(pre_missing_addr - pre_missing_both) + (pre_missing_value - pre_missing_both) + pre_missing_both:,})")

        # query set: raw parcel_id as stored on the board, plus its
        # punctuation-stripped form (an IN-clause needs an exact string match,
        # unlike enrichment_owner_mailing.py's per-lead LIKE matching).
        pins_to_query: set[str] = set()
        for _key, pid, _cur in candidates:
            pins_to_query.add(pid)
            pins_to_query.add(_strip_pid(pid))
        pins_to_query.discard("")

        print(f"\n[{time.strftime('%H:%M:%S')}] live-querying {len(pins_to_query):,} "
              f"TMS variants for {len(candidates):,} candidates...", flush=True)
        t0 = time.time()
        live = asyncio.run(_fetch_anderson_by_tms(pins_to_query))
        print(f"  live-matched {len(live):,} distinct TMS strings in "
              f"{int(time.time() - t0)}s", flush=True)

        live_by_stripped: dict[str, dict] = {}
        for p, a in live.items():
            live_by_stripped.setdefault(_strip_pid(p), a)

        now_iso = datetime.now(timezone.utc).isoformat()
        patches: dict[str, dict] = {}
        # Independent per-field tallies, derived from the SAME loop that builds
        # `patches`, so the headline number and this breakdown cannot diverge
        # (the Gaston lesson: don't report one number and silently build a
        # differently-scoped dict).
        field_tally: Counter = Counter()
        for key, pid, cur in candidates:
            attrs = live.get(pid) or live.get(_strip_pid(pid)) or live_by_stripped.get(_strip_pid(pid))
            if attrs is None:
                stats["not_found_live"] += 1
                continue
            raw_situs = _join(attrs, _SPEC["situs"]) if _SPEC.get("situs") else ""
            cleaned_addr = _clean_situs(raw_situs)
            val = _extract_value(attrs)
            patch: dict = {}
            if cleaned_addr and _is_missing_addr(cur.get("street_address")):
                patch["street_address"] = cleaned_addr
                field_tally["street_address"] += 1
            if val:
                for f in _VALUE_FIELDS:
                    if _is_missing_value(cur.get(f)):
                        patch[f] = val
                        field_tally[f] += 1
            if not patch:
                # Genuinely no new data (e.g. a parcel whose live PHYS_ADDR/
                # MRKT_VALUE is itself blank/zero) -- a legitimate outcome, not
                # a failure. See module docstring.
                stats["live_no_new_data"] += 1
                continue
            patch["raw"] = {"anderson_situs_value_backfill": {
                "ts": now_iso, "tms_queried": pid,
                "tms_live": attrs.get(_PIN_FIELD),
                "street_address": patch.get("street_address"),
                "value": val,
            }}
            patches[key] = patch
            stats["matched"] += 1

        print("\n=== match stats ===")
        for k, v in sorted(stats.items()):
            print(f"  {v:7,d}  {k}")
        print(f"\n=== verified per-field patch breakdown (from the patches actually "
              f"built, not a separate estimate) ===")
        for f in ("street_address", *_VALUE_FIELDS):
            print(f"  {field_tally.get(f, 0):7,d}  would newly fill {f}")
        addr_and_value = sum(
            1 for p in patches.values()
            if "street_address" in p and any(f in p for f in _VALUE_FIELDS)
        )
        print(f"  {addr_and_value:7,d}  patches that fill BOTH street_address and a value field")
        print(f"\ntotal patches ready: {len(patches):,}  (== {stats['matched']:,} "
              f"from match stats, must match)")
        assert len(patches) == stats["matched"], (
            "patches dict size diverged from the matched counter -- "
            "investigate before trusting either number")

        if args.dry_run:
            print("\nDRY RUN -- nothing written.")
            return 0

        result = patch_existing_rows(
            patches, {"backfill_anderson_situs_value": f"{len(patches)} rows"},
            docs_dir=docs)
        print("\n=== patch_existing_rows result ===")
        for k, v in result.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
