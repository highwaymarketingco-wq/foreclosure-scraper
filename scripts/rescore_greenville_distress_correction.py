#!/usr/bin/env python3
"""Recompute + republish raw['distress_stack'] for the Greenville County SC parcels
whose INPUT SIGNALS were corrected by scripts/backfill_greenville_distress_correction.py
--execute (commit d1fe4056, 2026-10-01).

WHY THIS EXISTS
    d1fe4056 removed a fabricated raw['distressed']=True PROPERTY-category signal
    (greenville_hard_distress.py bug, fixed in commit 2756b299) from 1,475 board rows.
    That commit's own message, and backfill_greenville_distress_correction.py's own
    end-of-run note, are explicit that it corrects INPUTS ONLY:

        "this patch corrects the INPUT signals only (raw['distressed'],
        raw['greenville_distress_correction'] provenance). Per the correction
        script's own design, it does not rewrite raw['distress_stack'] itself --
        the 526 tier changes above are what the NEXT scripts/patch_distress_score.py
        scoring pass will produce; the board's displayed tier (including the 8 HOT
        labels) is unchanged until that pass runs."

    This script IS that next pass -- scoped to exactly the rows that need it,
    using the safe streaming/patch primitives this repo now requires, not the
    whole-board scripts/patch_distress_score.py literally named above.

WHY NOT scripts/patch_distress_score.py AS-IS (read it first; this is not a
guess). It was written 2026-09-21, before the board-size-ceiling crisis
(2026-09-30, HANDOFF.md item 15) and the streaming-API migrations that followed.
Three independent, sufficient reasons not to run it today:

  1. UNSAFE MEMORY PATTERN. It calls web_artifact.read_board_json(path) -- a
     single json.loads() of the WHOLE docs/listings.json (currently 2,526,345,296
     bytes / ~2,409 MB, 219,143 rows) into one list[dict] with NO size gate at
     all (read_board_json has none; it is not load_board()), then
     Listing.model_validate()s EVERY one of those 219,143 rows (not just the
     1,475 that need it), runs score_board() over the ENTIRE board (board-wide
     parcel grouping, same cost as a full rescore), and finally
     json.dumps(data) + path.write_text() the WHOLE board back out as one
     in-memory string. That is the full dict list + the full Listing list + the
     full output string alive at once -- the exact "double materialization"
     pattern patch_existing_rows() was built specifically to replace (see that
     function's own docstring), on a board already measured to self-refuse at
     load_board()'s BOARD_LOAD_MAX_SOURCE_MB (1,200 MB) and separately measured
     at an 11+ GB physical footprint even after a streaming fix elsewhere
     (HANDOFF.md item 9). On this machine (8 GB, ~80 MB free / ~72% of 5 GB
     swap used at the time this script was written) that is not survivable.
  2. WRONG SCOPE even with infinite memory. score_board() groups and re-tiers
     every parcel on the WHOLE board, not just the 1,475 Greenville rows that
     actually changed -- touching (and risking) ~217,000 untouched rows to fix
     1,475 known ones.
  3. STALE PUBLISH MODEL. It bypasses write_artifact()/patch_existing_rows()
     entirely (hand-writes listings.json, then calls reseal_board()) and its own
     comment assumes "the next write_artifact() caller ... loads it through
     load_board() and re-emits" -- which is no longer true now that load_board()
     self-refuses above 1,200 MB on today's board. Adapting it line-by-line would
     mean replacing nearly every line (the load, the scope, and the publish
     model), which is a rewrite in substance; this script instead reuses the
     REAL scoring functions (distress_score._parcel_key/_score_group/
     flip_outside_footprint/_copy_ds -- never reimplemented) through the same
     constant-memory primitives (board_stream.iter_board_rows(),
     web_artifact.patch_existing_rows()) backfill_greenville_distress_correction.py
     already proved correct for this exact dataset.

SCOPE AND GROUPING. distress_score.score_board() computes ONE distress_stack per
PARCEL GROUP (distress_score._parcel_key(): state + county + parcel_id) and
copies it onto every listing in that group ("each listing gets its OWN copy: a
shared dict meant enrich_board_quality's in-place downrank on one sibling
re-tiered every other listing on the parcel"). A correct rescore therefore
cannot just touch the 1,475 corrected rows in isolation -- it must find each
one's full parcel group (which could include an uncorrected sibling row from a
different source on the same parcel) and recompute the GROUP. This script
streams every Greenville County SC row (not just the corrected ones) to
reconstruct the exact groups score_board() would form -- _parcel_key is
state:county:parcel_id and never crosses a county line, so Greenville-SC-only
scoping is sufficient, the same scoping backfill_greenville_distress_correction.py's
dry run already used and verified against the live board (0 mismatches against
the then-published distress_stack) -- then rescales only the groups that
contain at least one corrected row.

VERIFIED EMPIRICALLY (2026-10-01, this session, read-only probes against the
live board, no write): all 1,475 corrected rows sit in their OWN singleton
parcel group -- 0 of them share a _parcel_key() group with any other row (5
genuine 2-row parcel groups exist among Greenville's 3,268 rows, none touch a
corrected row); 0 are sold_confirmed; 0 are flip_outside_footprint; 0 have a
dedupe_key() collision anywhere on the 219,143-row board. So for TODAY's board
this reduces to one independent row per group, but the code below does not
assume that -- it is written for the general (multi-row-group) case and simply
found the simple case empirically true today.

RE-VALIDATION AGAINST THE ORIGINAL DRY RUN. Each corrected row already carries
the ORIGINAL 31dc92aa dry-run's own per-row prediction, stamped by d1fe4056's
patch: raw['greenville_distress_correction']['tier_before'/'tier_after']. This
script's own freshly recomputed tier is compared against that stored prediction
for every row as an independent cross-check (0 mismatches found, this session).

MEMORY SAFETY: read-only board access is board_stream.iter_board_rows()
(constant memory streaming), never web_artifact.load_board(). The (default)
dry-run touches the board only via streaming reads. The --execute path uses
web_artifact.patch_existing_rows() under board_lock(), the same bounded-memory
mutate-in-place primitive backfill_greenville_distress_correction.py's own
--execute path used for d1fe4056 (peak RSS 1.84 GB that run). The live board
(docs/listings.json, ~2,409 MB) is over BOARD_PATCH_MAX_SOURCE_MB (2,300 MB), so
--execute needs BOARD_PATCH_ALLOW_LARGE=1, run supervised with an external
RSS + physical-footprint watchdog, same as every other large-board patch in
this repo.

USAGE
    .venv/bin/python scripts/rescore_greenville_distress_correction.py
        (DEFAULT: dry-run. Reports the breakdown below. Writes nothing.)

    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python \\
        scripts/rescore_greenville_distress_correction.py --execute
        (Patches only rows whose dedupe_key() is unique board-wide -- see the
        collision guard below; 0 expected, per the empirical check above.)
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.dedupe import suspicious_parcel_keys  # noqa: E402
from foreclosure_scraper.distress_score import (  # noqa: E402
    OUT_OF_FOOTPRINT, _copy_ds, _parcel_key, _score_group, flip_outside_footprint,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, BoardLockBusy, board_lock, patch_existing_rows,
)

_RANK = {"COLD": 0, "WARM": 1, "HOT": 2}
_BOARD_GZ = "listings.json.gz"
_MARKER = "greenville_distress_correction"   # stamped by d1fe4056's backfill
_FIX_COMMIT = "2756b299"
_INPUT_CORRECTION_COMMIT = "d1fe4056"

_CAPPED_STACK = {
    "tier": "COLD", "stack": 0, "categories": [], "signals": [], "score": 0,
    "equity_band": None, "absentee": False, "out_of_state": False, "contactable": False,
    "surviving_senior_debt_risk": False, "scope_capped": OUT_OF_FOOTPRINT,
}


# --------------------------------------------------------------------------- #
# identity / filtering -- mirrors backfill_greenville_distress_correction.py exactly
# so a key computed here matches what that script (and patch_existing_rows()) use.
# --------------------------------------------------------------------------- #
def _norm_county(county) -> str:
    return re.sub(r"\s+county$", "", (county or "").strip(), flags=re.I).strip().lower()


def _is_greenville_sc(rec: dict) -> bool:
    return ((rec.get("state") or "").strip().upper() == "SC"
            and _norm_county(rec.get("county")) == "greenville")


def _is_corrected(rec: dict) -> bool:
    raw = rec.get("raw") or {}
    return isinstance(raw.get(_MARKER), dict)


def _light_key(rec: dict) -> str | None:
    light = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply unmatched
        return None


def _hydrate(d: dict) -> Listing | None:
    fields = {k: v for k, v in d.items() if k in Listing.model_fields}
    for ef, enum in (("listing_type", ListingType), ("property_kind", PropertyKind)):
        if isinstance(fields.get(ef), str):
            try:
                fields[ef] = enum(fields[ef])
            except ValueError:
                fields.pop(ef, None)
    try:
        li = Listing.model_validate(fields)
    except Exception:
        return None
    li.raw = d.get("raw") or {}
    return li


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true",
                    help="Actually patch the board. DEFAULT IS DRY-RUN (report only, "
                         "writes nothing).")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap patched rows (testing only; the report always covers everything found).")
    args = ap.parse_args()

    docs = REPO / "docs"
    today = date.today()

    print(f"[{time.strftime('%H:%M:%S')}] streaming board (one pass: whole-board dedupe_key "
          f"collision index + Greenville County SC rows) ...", flush=True)
    t0 = time.time()
    key_counts: Counter = Counter()
    gv_recs: list[dict] = []
    scanned = 0
    for rec in iter_board_rows(docs / _BOARD_GZ):
        scanned += 1
        k = _light_key(rec)
        if k is not None:
            key_counts[k] += 1
        if _is_greenville_sc(rec):
            gv_recs.append(rec)
    print(f"  scanned {scanned:,} board rows in {time.time() - t0:.0f}s; "
          f"Greenville County SC rows: {len(gv_recs):,}", flush=True)

    corrected_recs = [r for r in gv_recs if _is_corrected(r)]
    print(f"  rows carrying the '{_MARKER}' provenance marker "
          f"(stamped by {_INPUT_CORRECTION_COMMIT}): {len(corrected_recs):,}", flush=True)
    if not corrected_recs:
        print("\nNo corrected rows found. Nothing to rescore.")
        return 0

    # Hydrate ALL Greenville SC rows (not just the corrected ones) -- a correct rescore needs
    # each corrected row's FULL parcel group, which could include an uncorrected sibling.
    listings: list[Listing] = []
    rec_by_id: dict[int, dict] = {}
    hydrate_failed = 0
    for rec in gv_recs:
        li = _hydrate(rec)
        if li is None:
            if _is_corrected(rec):
                hydrate_failed += 1
            continue
        listings.append(li)
        rec_by_id[id(li)] = rec
    if hydrate_failed:
        print(f"  WARNING: {hydrate_failed:,} corrected row(s) could not be hydrated into a "
              f"Listing (malformed model fields) -- excluded from the rescore below.", flush=True)

    suspicious = suspicious_parcel_keys(listings)
    groups: dict[str, list[Listing]] = defaultdict(list)
    for li in listings:
        groups[_parcel_key(li, suspicious)].append(li)

    stats: Counter = Counter()
    mismatches_vs_gc_prediction: list[tuple] = []
    patch_rows: list[dict] = []

    for key, group in groups.items():
        corrected_members = [li for li in group if _is_corrected(rec_by_id[id(li)])]
        if not corrected_members:
            continue
        stats["groups_touched"] += 1
        stats["corrected_rows_in_group"] += len(corrected_members)
        if len(group) > len(corrected_members):
            stats["groups_with_uncorrected_sibling"] += 1

        active_all = [li for li in group if not (li.raw or {}).get("sold_confirmed")]
        if not active_all:
            # Every listing on this parcel is sold -- score_board() POPS distress_stack
            # entirely rather than publishing one. patch_existing_rows() only MERGES a raw
            # update (it cannot delete a key), so this case cannot be safely auto-patched;
            # flag it for manual review rather than guess. Not expected on today's data
            # (verified empirically: 0 of 1,475 corrected rows are sold_confirmed).
            stats["all_sold_groups_SKIPPED"] += 1
            for li in group:
                rec = rec_by_id[id(li)]
                if _is_corrected(rec):
                    print(f"  SKIPPING (all-sold parcel group, cannot auto-patch): "
                          f"source={rec.get('source')!r} parcel={rec.get('parcel_id')!r}")
            continue

        capped = [li for li in active_all if flip_outside_footprint(li)]
        active = [li for li in active_all if not flip_outside_footprint(li)]

        results: list[tuple[Listing, dict]] = [(li, dict(_CAPPED_STACK)) for li in capped]
        if active:
            ds = _score_group(active, {}, today)
            results.extend((li, _copy_ds(ds)) for li in active)

        for li, new_ds in results:
            rec = rec_by_id[id(li)]
            raw = rec.get("raw") or {}
            published = raw.get("distress_stack") or {}
            tier_before = published.get("tier")
            tier_after = new_ds.get("tier")

            if _is_corrected(rec):
                gc = raw.get(_MARKER) or {}
                predicted_before, predicted_after = gc.get("tier_before"), gc.get("tier_after")
                if (tier_before, tier_after) != (predicted_before, predicted_after):
                    mismatches_vs_gc_prediction.append(
                        (rec.get("source"), rec.get("parcel_id"),
                         tier_before, tier_after, predicted_before, predicted_after))

            if new_ds == published:
                stats["rows_unchanged"] += 1
                continue

            stats["rows_changed"] += 1
            if tier_before != tier_after:
                stats[f"transition:{tier_before}->{tier_after}"] += 1
                rb, ra = _RANK.get(tier_before, -1), _RANK.get(tier_after, -1)
                if ra < rb:
                    stats["tier_downgrade_rows"] += 1
                elif ra > rb:
                    stats["tier_upgrade_rows"] += 1
            else:
                stats["same_tier_other_field_changed"] += 1

            key_r = _light_key(rec)
            patch_rows.append({
                "key": key_r,
                "key_collision": bool(key_r) and key_counts.get(key_r, 0) > 1,
                "source": rec.get("source"), "parcel_id": rec.get("parcel_id"),
                "county": rec.get("county"), "state": rec.get("state"),
                "street_address": rec.get("street_address"),
                "tier_before": tier_before, "tier_after": tier_after,
                "was_corrected_row": _is_corrected(rec),
                "new_distress_stack": new_ds,
            })

    # ---- report -------------------------------------------------------------------
    print("\n=== Greenville County SC distress_stack rescore: DRY-RUN REPORT ===")
    print(f"Corrected rows found (marker): {len(corrected_recs):,}")
    print(f"Parcel groups touched: {stats['groups_touched']:,}")
    print(f"  groups with an UNCORRECTED sibling row: {stats['groups_with_uncorrected_sibling']:,} "
          f"(expected 0 on today's board -- verified empirically before this script was written)")
    print(f"  all-sold groups skipped (cannot auto-patch): {stats['all_sold_groups_SKIPPED']:,}")

    print(f"\nRow-level outcome ({stats['rows_changed'] + stats['rows_unchanged']:,} rows in "
          f"touched groups):")
    print(f"  distress_stack UNCHANGED : {stats['rows_unchanged']:,}")
    print(f"  distress_stack CHANGED   : {stats['rows_changed']:,}")
    print(f"    tier DOWNGRADE : {stats['tier_downgrade_rows']:,}")
    for k in sorted(stats):
        if k.startswith("transition:"):
            before, after = k.split(":", 1)[1].split("->")
            if _RANK.get(after, -1) < _RANK.get(before, -1):
                print(f"        {k.split(':', 1)[1]:>12}: {stats[k]:,}")
    print(f"    tier UPGRADE   : {stats['tier_upgrade_rows']:,}")
    for k in sorted(stats):
        if k.startswith("transition:"):
            before, after = k.split(":", 1)[1].split("->")
            if _RANK.get(after, -1) > _RANK.get(before, -1):
                print(f"        {k.split(':', 1)[1]:>12}: {stats[k]:,}")
    print(f"    same tier, other field changed (e.g. signals/score/categories): "
          f"{stats['same_tier_other_field_changed']:,}")

    print(f"\nCross-check against the ORIGINAL 31dc92aa dry-run's per-row prediction "
          f"(stamped on each corrected row by d1fe4056's patch):")
    if mismatches_vs_gc_prediction:
        print(f"  MISMATCH on {len(mismatches_vs_gc_prediction):,} row(s) -- investigate before "
              f"trusting --execute. First 5:")
        for src, pid, tb, ta, ptb, pta in mismatches_vs_gc_prediction[:5]:
            print(f"    source={src!r} parcel={pid!r} recomputed={tb!r}->{ta!r} "
                  f"predicted={ptb!r}->{pta!r}")
    else:
        print(f"  MATCH on all {len(corrected_recs):,} corrected rows -- this script's fresh "
              f"recompute agrees exactly with the original dry run's stored prediction.")

    collide = sum(1 for r in patch_rows if r["key_collision"])
    no_key = sum(1 for r in patch_rows if r["key"] is None)
    print(f"\nWhole-board dedupe_key() collision guard (patch rows only):")
    print(f"  safely patchable (unique key board-wide): {len(patch_rows) - collide - no_key:,}")
    print(f"  SKIPPED -- key collides elsewhere on the board: {collide:,}")
    print(f"  SKIPPED -- row could not be keyed at all: {no_key:,}")

    if args.limit:
        patch_rows = patch_rows[:args.limit]

    if not args.execute:
        print("\nDRY RUN -- nothing written. Re-run with --execute (and "
              "BOARD_PATCH_ALLOW_LARGE=1) to apply.")
        return 0

    # ---- execute --------------------------------------------------------------------
    now_iso = datetime.now(timezone.utc).isoformat()
    patches: dict[str, dict] = {}
    skipped_unsafe = 0
    for row in patch_rows:
        if row["key"] is None or row["key_collision"]:
            skipped_unsafe += 1
            continue
        patches[row["key"]] = {"raw": {
            "distress_stack": row["new_distress_stack"],
            "greenville_distress_rescore": {
                "ts": now_iso, "fix_commit": _FIX_COMMIT,
                "input_correction_commit": _INPUT_CORRECTION_COMMIT,
                "tier_before": row["tier_before"], "tier_after": row["tier_after"],
            },
        }}

    print(f"\n[{time.strftime('%H:%M:%S')}] applying {len(patches):,} patches "
          f"({skipped_unsafe:,} skipped as unsafe to key) ...", flush=True)
    try:
        with board_lock(REPO, owner="rescore_greenville_distress_correction"):
            result = patch_existing_rows(
                patches,
                {"rescore_greenville_distress_correction": f"{len(patches)} rows"},
                docs_dir=docs)
    except BoardLockBusy as exc:
        print(f"{exc} -- another board writer is active. Nothing written.", flush=True)
        return 1
    print("=== patch_existing_rows result ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
