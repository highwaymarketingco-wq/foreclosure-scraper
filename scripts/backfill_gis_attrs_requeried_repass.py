#!/usr/bin/env python3
"""ONE-TIME re-pass for rows this mechanism already marked DONE while the 2026-11-15
_TOP_FIELDS bug (commit 535e71d0) was live.

WHY THIS EXISTS. backfill_gis_attrs_boardwide.py's and backfill_lexington_gis_attrs.py's
_TOP_FIELDS tuple never named `bedrooms`/`bathrooms`, so every prior batch of EITHER
script computed real bedroom/bathroom fills in memory (parcel_cache_join.apply_hit() sets
them whenever a cache hit carries them) and then silently dropped them from the patch
written to the board, because that tuple -- not just the before/after snapshot but also
the per-field patch-extraction loop -- never carried those two names. Both scripts' own
candidate-selection loops treat `raw["gis"]["queried"]` truthy as "already done" and skip
such a row forever on every future run, so the fix alone (already shipped, both scripts,
commit 535e71d0) does nothing for a row THIS already happened to. That is the gap this
script closes: a dedicated re-pass over exactly those rows, board-wide, every county.

REAL SCOPE (re-derived 2026-11-15/16 by streaming the board fresh -- see
docs/../memory project_gis_attrs_topfields_repass_2026-11-16.md for the full number and
the per-county breakdown; DO NOT trust a stale estimate, re-run the equivalent scan if
this script is reused later): candidates = board rows with raw.gis.queried truthy
(already processed by this mechanism, by either script), a parcel_id (required --
parcel_cache is keyed by county+parcel_id, never by lat/lng), listing_type is not
tax_sale_overage, and bedrooms is None or bathrooms is None (still missing at least one).

HOW THIS IS SAFE AND FAST. Every OTHER field this mechanism can fill either comes from
the LIVE GIS query path (which a `queried=True` row, by definition, already went through
at least once -- re-running it would mean a fresh network round-trip to re-derive data
this script has no reason to touch) or from the SAME local parcel_cache join the two
existing scripts already run as an unconditional first step inside enrich_gis_attrs()
(see parcel_cache_join.join_listings(), called there over EVERY listing before its own
per-lead idempotency gate even runs -- confirmed by reading enrichment_gis_attrs.py
2026-11-15/16). Since bedrooms/bathrooms are ONLY ever filled by that local join
(parcel_cache_join.apply_hit(), fill-only: `if beds and ... and not li.bedrooms:`), this
script calls `join_listings()` DIRECTLY instead of the full enrich_gis_attrs() --
bypassing the live-query path entirely rather than forcing a re-query
(FORECLOSURE_GIS_FORCE=1) that would be slower, network-bound, rate-limited, and pointless
for a field this join already fully owns. No live network query is made by this script at
all; every candidate row is resolved purely from the local parcel_cache SQLite files
already on disk. The GLOBAL shared-fallback-point pre-pass the other two scripts run is
also skipped on purpose: it exists only to protect the LIVE point-query path
(block_binding.imprecise_point()), which join_listings()/apply_hit() never touch.

FILL-ONLY, SAME AS THE OTHER TWO SCRIPTS. join_listings()/apply_hit() never overwrites a
field a row already has (`and not li.bedrooms`, `and not li.bathrooms`, etc.) -- but to
make that guarantee hold for a Listing object THIS script builds in memory, the candidate
Listing must start with its REAL current bedrooms/bathrooms values, not pydantic's field
default (None). (A subtle trap: the existing scripts' own _LIGHT_FIELDS tuple does not
carry bedrooms/bathrooms into model_construct() at all -- harmless for them, since their
candidate pool is rows that have NEVER been queried, where both fields are genuinely still
None on the real board too. This script's candidate pool can have ONE of the two already
set -- "only one of bedrooms/bathrooms missing" was 176 of 73,694 rows in the 2026-11-16
scope scan -- so _LIGHT_FIELDS is extended here with bedrooms/bathrooms explicitly, or a
row with a real bedrooms=3 and a missing bathrooms would start life in this script as
bedrooms=None, and a cache hit carrying a DIFFERENT bedroom count would silently overwrite
the real value instead of leaving it alone.)

CHUNKING. Pass --counties as a comma-separated list of "ST:County" tokens (exactly the
rec["state"]:rec["county"] strings as stored on the board, e.g. "NC:Gaston,SC:Horry") to
scope one run to a batch of counties -- this script makes no live network calls, but
still builds one lightweight Listing object per candidate row in memory, so a board-wide
run of ~70k+ candidates is chunked into a few county-grouped batches on an 8GB machine
with other processes already running, same caution the boardwide script's own --max-rows
exists for. Omit --counties to process every candidate on the board in one pass.

    python scripts/backfill_gis_attrs_requeried_repass.py --dry-run --counties "NC:Gaston"
    BOARD_PATCH_ALLOW_LARGE=1 python scripts/backfill_gis_attrs_requeried_repass.py \
        --allow-large --counties "NC:Gaston"
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from backfill_gis_attrs_boardwide import (  # noqa: E402  (reuse, do not redefine)
    _LIGHT_FIELDS as _BW_LIGHT_FIELDS, _NEEDED_RAW_KEYS, _RAW_WATCH_KEYS, _TOP_FIELDS,
)
from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.parcel_cache_join import join_listings  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLockBusy, board_lock, board_patch_size_state, patch_existing_rows,
)

# _TOP_FIELDS already names bedrooms/bathrooms (the 2026-11-15 fix) -- also put them in
# the fields used to build each candidate Listing, so a row with only ONE of the two
# missing starts this script with its REAL current value in the other, not pydantic's
# None default (see module docstring "FILL-ONLY" section).
_LIGHT_FIELDS = tuple(dict.fromkeys(_BW_LIGHT_FIELDS + ("bedrooms", "bathrooms")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-large", action="store_true")
    ap.add_argument("--counties", type=str, default="",
                    help='comma-separated "ST:County" tokens to scope this run to '
                         '(e.g. "NC:Gaston,SC:Horry"); omit for every county')
    args = ap.parse_args()

    county_filter = None
    if args.counties.strip():
        county_filter = {tuple(tok.strip().split(":", 1))
                          for tok in args.counties.split(",") if tok.strip()}
        print(f"scoped to {len(county_filter)} county token(s): {sorted(county_filter)}")

    docs_dir = REPO / "docs"
    if not args.dry_run:
        size_state = board_patch_size_state(docs_dir)
        if not size_state["ok"] and not args.allow_large:
            print(f"REFUSING: {size_state['reason']}. Re-run with --allow-large.")
            return 1

    print("streaming board, selecting already-queried rows still missing "
          "bedrooms and/or bathrooms (no live network query path reached by this "
          "script -- see module docstring)...")
    keyed: dict[str, Listing] = {}
    before: dict[str, dict] = {}
    not_queried = 0
    no_parcel_id = 0
    tax_sale_overage = 0
    not_in_county_filter = 0
    already_has_both = 0
    for rec in iter_board_rows(docs_dir / "listings.json.gz"):
        full_raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        if not (full_raw.get("gis") or {}).get("queried"):
            not_queried += 1
            continue
        bedrooms, bathrooms = rec.get("bedrooms"), rec.get("bathrooms")
        if bedrooms is not None and bathrooms is not None:
            already_has_both += 1
            continue
        pid = rec.get("parcel_id")
        if not pid or not str(pid).strip():
            no_parcel_id += 1
            continue
        if (rec.get("listing_type") or "") == "tax_sale_overage":
            tax_sale_overage += 1
            continue
        if county_filter is not None:
            tok = (rec.get("state") or "", rec.get("county") or "")
            if tok not in county_filter:
                not_in_county_filter += 1
                continue
        li = Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})
        li.raw = {k: full_raw[k] for k in _NEEDED_RAW_KEYS if k in full_raw}
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        keyed[key] = li
        # deepcopy: apply_hit() can mutate raw['gis'] (li.raw.setdefault("gis", {})[...] =
        # ...) in place -- a shallow snapshot would hold the SAME dict object and silently
        # "see" the mutation too (the exact trap backfill_gis_attrs_boardwide.py's own
        # before/after snapshot documents and avoids).
        before[key] = {**{f: getattr(li, f, None) for f in _TOP_FIELDS},
                       **{k: copy.deepcopy(li.raw.get(k)) for k in _RAW_WATCH_KEYS}}

    print(f"rows loaded this run: {len(keyed):,} "
          f"(skipped: {not_queried:,} never queried by this mechanism, "
          f"{already_has_both:,} already have both bedrooms and bathrooms, "
          f"{no_parcel_id:,} queried+missing but no parcel_id (parcel_cache join needs "
          f"one -- cannot be resolved by this script), "
          f"{tax_sale_overage:,} tax_sale_overage (current-owner fields are not this "
          f"listing's claimant, same exclusion join_listings() itself applies), "
          f"{not_in_county_filter:,} outside --counties scope)")

    if not keyed:
        print("nothing to do.")
        return 0

    jc = join_listings(list(keyed.values()))
    print(f"join_listings stats: {dict(jc)}")

    patches: dict[str, dict] = {}
    for key, li in keyed.items():
        after = {**{f: getattr(li, f, None) for f in _TOP_FIELDS},
                 **{k: li.raw.get(k) if isinstance(li.raw, dict) else None
                    for k in _RAW_WATCH_KEYS}}
        if after == before[key]:
            continue
        patch: dict = {}
        for f in _TOP_FIELDS:
            if after[f] != before[key][f]:
                patch[f] = after[f]
        raw_patch = {k: after[k] for k in _RAW_WATCH_KEYS if after[k] != before[key][k]}
        if raw_patch:
            patch["raw"] = raw_patch
        if patch:
            patches[key] = patch

    print(f"rows changed: {len(patches):,}")
    beds_filled = sum(1 for p in patches.values() if "bedrooms" in p)
    baths_filled = sum(1 for p in patches.values() if "bathrooms" in p)
    print(f"  of those, bedrooms filled: {beds_filled:,}, bathrooms filled: {baths_filled:,}")
    if args.dry_run:
        print("DRY RUN -- nothing written.")
        for key, p in list(patches.items())[:5]:
            print("  ", key, {k: v for k, v in p.items() if k != "raw"},
                  "raw_keys_changed=", list(p.get("raw", {}).keys()))
        return 0
    if not patches:
        print("nothing to patch.")
        return 0

    try:
        with board_lock(REPO, owner="backfill_gis_attrs_requeried_repass", wait=3600, poll=10):
            pstats = patch_existing_rows(
                patches, {"backfill_gis_attrs_requeried_repass": len(patches)},
                docs_dir=docs_dir)
    except BoardLockBusy as exc:
        print(f"{exc} -- refusing to write ({len(patches):,} patches from this "
              f"invocation are lost; re-run to redo them and retry).")
        return 1
    print(f"patch_existing_rows: {pstats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
