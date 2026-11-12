#!/usr/bin/env python3
"""DRY-RUN ONLY as of this commit -- NOT YET EXECUTED against the board.

Corrects board rows poisoned by the fabricated raw['distressed'] = True flag
that scripts/../src/foreclosure_scraper/scrapers/counties_sc/greenville_hard_distress.py
used to stamp (commit 2756b299, 2026-09-30, fixed the same day it was found).

WHY THIS EXISTS
    The old code: `if probate or (tax_sale and tax_owed): raw["distressed"] = True`.
    distress_score._distressed_flag_counts() reads raw['distressed'] as a PROPERTY
    (physical-condition) signal. Neither a probate/estate match (a LIFE_EVENT fact)
    nor a tax-sale balance (already FINANCIAL via listing_type=TAX_LIEN + the
    recorded_debt/tax_lien signal) is physical-condition evidence, so the flag
    fabricated a second category on top of one real event -- a fake stack of 2 from
    a single fact, the same bug class already fixed for
    pickens_delinquent_parcels.py's chronic-delinquency flag (F5, 2026-09-21).

    The fix changed what a FUTURE scrape writes. It does nothing for rows already
    on the board. And because Listing.merge() deep-merges raw across same-parcel
    duplicates, and greenville_hard_distress's OWN rows lose essentially every
    parcel-merge race to two OTHER Greenville sources (counties_generic.
    arcgis_distress_layers' greenville_unpaid_tax_parcels layer, same GIS query
    same PINs; counties_sc.greenville_delinquent_tax, same tax-sale roster page) --
    see that scraper's own "ZERO-NET-NEW AUDIT" docstring section -- the fabricated
    flag is not confined to greenville_hard_distress's own (nearly absent) board
    rows. It leaked into whatever OTHER source's row won the merge for that parcel,
    under THAT source's name. `raw['distressed']` is "*" in web_artifact.RAW_KEEP
    (always has been), so the flag survives publish and is sitting on the live
    board today exactly as merged.

    A raw dict key, once merged in, is never removed by a later merge that simply
    doesn't set it again (Listing.merge()'s own docstring: "_deep_merge_dict unions
    DICT KEYS ... a key ABSENT from a dict is invisible to it, so it can never
    delete one"). So the scraper fix alone cannot self-heal the board; a dedicated
    correction pass is needed. This script is that pass's DRY-RUN half.

WHY `raw['distressed'] is True` (STRICT BOOLEAN) IS THE RIGHT FILTER, NOT JUST
"truthy", AND NOT JUST "county == Greenville, SC":
    `raw['distressed']` is not a Greenville-only key. Exhaustively grepped every
    assignment site in src/ (2026-10-01):
      - 3 NC county scrapers set it literally True for real code-enforcement /
        vacant-structure condition hits (henderson_code_violations.py,
        hendersonville_vacant_structures.py, gastonia_code_enforcement.py) --
        all NC, never touch a Greenville County SC parcel.
      - 3 enrichers set it literally True off a REAL CAMA condition code
        (enrichment_sc_cama.py, enrichment_cama_condition.py,
        enrichment_owner_mailing.py's CAMA-distress join) -- but NONE of them
        ever fires for Greenville County SC specifically: sc_assessor_cama.
        SC_CAMA only covers Spartanburg + Anderson; enrichment_cama_condition.
        CAMA_SOURCES only covers NC Buncombe/Carteret/Onslow + SC York; and
        enrichment_owner_mailing's Greenville path is the generic SCDOT
        statewide fallback (_scdot_spec, no COUNTY_GIS["SC:Greenville"] entry),
        whose out_fields is DERIVED from the spec's owner/mail/situs/parcel
        columns only (_spec_out_fields) -- it never requests a condition
        column, so _extract_distress() never has one to read for Greenville.
      - national.homeharvest_distressed.py ALSO sets raw['distressed'], but to
        a DICT (`{"matched_keywords": [...], "mls_status": ..., ...}`), never to
        the literal boolean True -- a real (if weak) HomeHarvest keyword match
        can legitimately land on a Greenville address and must NOT be touched
        here. A dict is truthy in Python, so a naive "is this field truthy"
        filter would misclassify it as the bug; `is True` (identity on a
        literal bool) does not.
    Net: for a Greenville County SC row, `raw['distressed'] is True` has
    EXACTLY ONE possible origin on this codebase as of 2026-09-30 -- the now-
    fixed greenville_hard_distress.py line. No other scraper or enricher can
    produce that exact value for that county. The script still counts and
    reports the non-bool-truthy rows it deliberately excludes, so the filter's
    precision is visible, not just asserted.

WHAT "CORRECTED" MEANS, re-using distress_score's REAL functions (never
reimplemented):
    1. raw['distressed'] -> None (same scoring effect as the key being absent;
       _distressed_flag_counts() does `if not r.get("distressed"): return False`,
       so None and "missing" are indistinguishable to the scorer. Deliberately
       NOT deleting the key outright: patch_existing_rows() only ever MERGES a
       raw update via dict.update(), so a corrected row keeps a visible trace
       that this key was touched rather than looking like it was never set.)
    2. IF the merged row still carries raw['greenville_distress']['probate']
       (present when this scrape's merge landed AFTER 2026-09-23's RAW_KEEP fix
       for that sub-key -- commit 6be27f6d) -- add raw['probate'] with exactly
       the shape the FIXED scraper itself now writes (case_number/decedent/
       match_confidence), UNLESS the row already carries a raw['probate'] block
       from some other, independent source (never overwritten). This is the
       one case that can RAISE a tier: swapping a fabricated PROPERTY(8) signal
       for a real LIFE_EVENT(20) signal keeps the stack-count the same (still 2
       categories) but can lift the F5 "no category weight >= 15" stack-cap
       that a weak FINANCIAL category (e.g. recorded_debt=12) alone could not
       clear, or raise score enough to cross the WARM score>=28 line.
    3. If raw['greenville_distress'] never made it onto this row at all (the
       merge that planted raw['distressed'] happened BEFORE the 2026-09-23
       RAW_KEEP fix for that sub-key, and no later re-scrape of
       greenville_hard_distress has touched this parcel since), there is no
       provenance left on the published board to say whether the origin was a
       probate match or a tax-sale balance. The flag is still removed (it is
       fabricated either way -- see the exhaustive filter proof above), but no
       raw['probate'] is fabricated without evidence. Reported separately as
       probate_status=unknown_no_provenance.
    4. Each affected parcel's distress_stack tier is recomputed BOTH ways
       (current raw vs. corrected raw) through distress_score._score_group() and
       distress_score.flip_outside_footprint() directly -- the exact functions
       score_board() itself calls -- grouped by distress_score._parcel_key()
       (NOT dedupe_key(): a few parcels carry more than one board row under
       slightly different parcel-id punctuation that dedupe_key() treats as
       distinct rows but _parcel_key() correctly folds into one scoring group,
       exactly as score_board() does).

MEMORY SAFETY: read-only board access is scripts/board_stream.iter_board_rows()
(constant memory streaming), never web_artifact.load_board(). This dry-run does
not touch the board at all. The (not-yet-exercised) --execute path uses
web_artifact.patch_existing_rows() under board_lock(), the same bounded-memory
mutate-in-place primitive scripts/backfill_gaston_sqft_valtot.py uses -- the live
board (docs/listings.json, ~2.4 GB per the current manifest) is already over
BOARD_PATCH_MAX_SOURCE_MB (2,300 MB), so --execute will need
BOARD_PATCH_ALLOW_LARGE=1, run supervised, same as every other large-board patch
in this repo.

USAGE
    .venv/bin/python scripts/backfill_greenville_distress_correction.py
        (DEFAULT: dry-run. Reports the breakdown below. Writes nothing.)

    BOARD_PATCH_ALLOW_LARGE=1 .venv/bin/python \\
        scripts/backfill_greenville_distress_correction.py --execute
        (NOT RUN by this session. Requires explicit --execute. Patches only rows
        whose dedupe_key() is unique board-wide -- see the collision guard below.)

TIER-IMPACT BREAKDOWN (2026-10-01 dry run against the live board; see the commit
message for full detail). Verified two independent ways: once via this script's
own per-parcel-group recompute, and a second time with a standalone one-off
script that re-reads the board and checks the published distress_stack directly
-- the two agreed on every number below, and a sampled before/after signal dump
(3 downgrades, 3 no-changes) confirmed the mechanism (removing the fabricated
8-point PROPERTY signal drops a 2-category stack to 1; whether the tier moves
depends on whether the row's score still clears the >=28 WARM floor on
FINANCIAL alone):

    Greenville County SC rows on the board:            3,268
    raw['distressed'] truthy (any type):                1,479
      of those, exactly `True` (the bug's signature):   1,479   <- ALL of them
      excluded as a different, legitimate signal:            0
    100% of the 1,479 share one source on today's board:
      counties_generic.arcgis_distress.greenville_unpaid_tax_parcels
      (exactly the collision the scraper's own "ZERO-NET-NEW AUDIT" predicts)

    Published tier BEFORE correction:    WARM 1,471   HOT 8
    Parcel groups recomputed:            1,479 (1:1 -- no multi-row parcel groups)
      DOWNGRADE : 526   (HOT->COLD 3, HOT->WARM 5, WARM->COLD 518)
      NO CHANGE : 953   (score still >= 28 on FINANCIAL alone after the PROPERTY
                         signal is removed, so the WARM score-floor route holds
                         even though the stack drops from 2 categories to 1)
      UPGRADE   :   0   (would only come from the probate side-effect add)

    Probate side-effect status, all 1,479 rows: unknown_no_provenance -- NONE of
    the affected rows still carry raw['greenville_distress']['probate'] on the
    published board (that merge predates, or was never refreshed after, the
    2026-09-23 RAW_KEEP fix for that sub-key). So although the ORIGINAL bug could
    fire from either a probate match or a tax-sale balance, there is currently NO
    way to tell, from published board data alone, which (if any) of these 1,479
    rows were probate matches -- the probate side-effect add this script supports
    cannot fire on today's board. It will fire automatically, with no code change
    needed, on any future row where a fresh greenville_hard_distress merge lands
    raw['greenville_distress']['probate'] before this script next runs.

    Dedupe-key collision guard: 1,475 safely patchable, 4 skipped (key shared by
    >1 board row elsewhere), 0 unkeyable.
"""
from __future__ import annotations

import argparse
import copy
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
    _parcel_key, _score_group, flip_outside_footprint,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    _APPEND_SIG_FIELDS, BoardLockBusy, board_lock, patch_existing_rows,
)

_RANK = {"COLD": 0, "WARM": 1, "HOT": 2}
_BOARD_GZ = "listings.json.gz"
_FIX_COMMIT = "2756b299"


# --------------------------------------------------------------------------- #
# identity / filtering
# --------------------------------------------------------------------------- #
def _norm_county(county) -> str:
    return re.sub(r"\s+county$", "", (county or "").strip(), flags=re.I).strip().lower()


def _is_greenville_sc(rec: dict) -> bool:
    return ((rec.get("state") or "").strip().upper() == "SC"
            and _norm_county(rec.get("county")) == "greenville")


def _bug_flag(raw: dict) -> bool:
    """The bug's EXACT signature -- strict boolean True. See module docstring for
    why this must not be relaxed to a generic truthiness check."""
    return isinstance(raw, dict) and raw.get("distressed") is True


def _light_key(rec: dict) -> str | None:
    """Same identity fields / same construction patch_existing_rows() itself uses
    (_APPEND_SIG_FIELDS), so a key computed here is guaranteed to match what a real
    --execute run would key against."""
    light = Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS})
    try:
        return light.dedupe_key()
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply unmatched
        return None


def _hydrate(d: dict) -> Listing | None:
    """Same pattern scripts/patch_distress_score.py's _hydrate() uses: coerce the
    two enums, validate everything else, then overwrite raw with the EXACT
    published dict (never re-validated/re-typed) so a correction mutates the real
    thing, not a schema-normalized copy of it."""
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
# the correction itself
# --------------------------------------------------------------------------- #
def _probate_from_provenance(raw: dict) -> dict | None:
    """What the FIXED scraper's own `if probate: raw["probate"] = {...}` line
    (commit 2756b299) would have written, reconstructed from whatever
    raw['greenville_distress']['probate'] survived the merge. None when that
    sub-block never made it onto this row (see module docstring, point 3)."""
    gv = raw.get("greenville_distress")
    if not isinstance(gv, dict):
        return None
    pro = gv.get("probate")
    if not isinstance(pro, dict):
        return None
    return {
        "case_number": pro.get("case") or pro.get("case_number"),
        "decedent": pro.get("name") or pro.get("decedent"),
        "match_confidence": pro.get("confidence") or pro.get("match_confidence"),
    }


def correct_raw(raw: dict) -> tuple[dict, dict]:
    """(corrected_raw, meta). Never mutates the input. meta['probate_status'] is
    one of:
      confirmed_from_greenville_distress_block  -- probate sub-dict present; added
      already_present_other_source              -- raw['probate'] pre-existed; left alone
      confirmed_lane_no_subdict                 -- lanes says probate fired but the
                                                    probate sub-dict itself didn't
                                                    survive -- reported, NOT fabricated
      confirmed_tax_sale_only                   -- greenville_distress present, no
                                                    probate lane: correctly nothing to add
      unknown_no_provenance                     -- greenville_distress block absent
                                                    entirely (pre-RAW_KEEP-fix merge);
                                                    flag still removed, nothing added
    """
    corrected = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    corrected["distressed"] = None
    meta = {"added_probate": False, "probate_status": "unknown_no_provenance"}

    gv = raw.get("greenville_distress") if isinstance(raw, dict) else None
    if raw.get("probate"):
        meta["probate_status"] = "already_present_other_source"
        return corrected, meta
    pro = _probate_from_provenance(raw)
    if pro:
        corrected["probate"] = pro
        meta["added_probate"] = True
        meta["probate_status"] = "confirmed_from_greenville_distress_block"
        return corrected, meta
    if isinstance(gv, dict):
        lanes = gv.get("lanes")
        if isinstance(lanes, list) and "probate_decedent_owner" in lanes:
            meta["probate_status"] = "confirmed_lane_no_subdict"
        else:
            meta["probate_status"] = "confirmed_tax_sale_only"
    return corrected, meta


def _group_tier(group: list[Listing], today: date) -> str:
    """Re-derive one parcel group's tier using distress_score's REAL functions --
    the same three steps score_board() itself runs per group."""
    active_all = [li for li in group if not (li.raw or {}).get("sold_confirmed")]
    if not active_all:
        return "COLD"
    active = [li for li in active_all if not flip_outside_footprint(li)]
    if not active:
        return "COLD"
    ds = _score_group(active, {}, today)
    return ds["tier"]


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true",
                    help="Actually patch the board. DEFAULT IS DRY-RUN (report only, "
                         "writes nothing). Do not pass this without reading the dry-run "
                         "report first -- this fix can DOWNGRADE tiers.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap patched rows (testing only; the report always covers everything found).")
    args = ap.parse_args()

    docs = REPO / "docs"
    today = date.today()

    print(f"[{time.strftime('%H:%M:%S')}] streaming board for Greenville County SC rows ...",
          flush=True)
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

    any_truthy = sum(1 for r in gv_recs if (r.get("raw") or {}).get("distressed"))
    strict_true = sum(1 for r in gv_recs if _bug_flag(r.get("raw") or {}))
    print(f"  raw['distressed'] truthy (any type): {any_truthy:,}")
    print(f"  of those, exactly `True` (the bug's own signature): {strict_true:,}")
    print(f"  excluded -- a DIFFERENT, legitimate signal (e.g. a HomeHarvest keyword "
          f"dict, not the literal bool): {any_truthy - strict_true:,}", flush=True)

    if strict_true == 0:
        print("\nNo genuinely affected rows found. Nothing to do.")
        return 0

    # Hydrate every Greenville SC row once, group by PARCEL (distress_score's own
    # grouping -- not dedupe_key -- so a parcel split across >1 board row by
    # formatting scores as one group, exactly like score_board() does).
    listings: list[Listing] = []
    rec_by_id: dict[int, dict] = {}
    hydrate_failed = 0
    for rec in gv_recs:
        li = _hydrate(rec)
        if li is None:
            if _bug_flag(rec.get("raw") or {}):
                hydrate_failed += 1
            continue
        listings.append(li)
        rec_by_id[id(li)] = rec
    if hydrate_failed:
        print(f"  WARNING: {hydrate_failed:,} affected row(s) could not be hydrated into a "
              f"Listing (malformed model fields) -- excluded from the tier recompute below, "
              f"counted separately.", flush=True)

    suspicious = suspicious_parcel_keys(listings)
    groups: dict[str, list[Listing]] = defaultdict(list)
    for li in listings:
        groups[_parcel_key(li, suspicious)].append(li)

    stats: Counter = Counter()
    probate_status_counts: Counter = Counter()
    mismatches: list[tuple] = []
    patch_rows: list[dict] = []

    for key, group in groups.items():
        flagged = [li for li in group if _bug_flag(li.raw)]
        if not flagged:
            continue
        stats["parcels_affected"] += 1
        stats["rows_affected"] += len(flagged)

        tier_before = _group_tier(group, today)
        for li in group:
            rec = rec_by_id[id(li)]
            published = ((rec.get("raw") or {}).get("distress_stack") or {}).get("tier")
            if published is not None and published != tier_before:
                mismatches.append((rec.get("source"), rec.get("parcel_id"),
                                   published, tier_before))

        corrected_group: list[Listing] = []
        row_metas: list[tuple[Listing, dict]] = []
        for li in group:
            if _bug_flag(li.raw):
                corrected_raw, meta = correct_raw(li.raw)
                li2 = li.model_copy(deep=False)
                li2.raw = corrected_raw
                corrected_group.append(li2)
                row_metas.append((li, meta))
                probate_status_counts[meta["probate_status"]] += 1
            else:
                corrected_group.append(li)

        tier_after = _group_tier(corrected_group, today)
        rank_before, rank_after = _RANK[tier_before], _RANK[tier_after]
        if rank_after < rank_before:
            stats["parcels_downgrade"] += 1
            stats[f"downgrade:{tier_before}->{tier_after}"] += 1
        elif rank_after > rank_before:
            stats["parcels_upgrade"] += 1
            stats[f"upgrade:{tier_before}->{tier_after}"] += 1
        else:
            stats["parcels_no_change"] += 1

        for li, meta in row_metas:
            rec = rec_by_id[id(li)]
            key_r = _light_key(rec)
            # Recompute (cheap, pure) rather than thread the corrected_group's copy
            # through row_metas -- keeps this loop's data flow obvious.
            cr, _m = correct_raw(li.raw)
            patch_rows.append({
                "key": key_r,
                "key_collision": bool(key_r) and key_counts.get(key_r, 0) > 1,
                "source": rec.get("source"),
                "county": rec.get("county"), "state": rec.get("state"),
                "parcel_id": rec.get("parcel_id"),
                "street_address": rec.get("street_address"),
                "tier_before": tier_before, "tier_after": tier_after,
                "probate_status": meta["probate_status"],
                "added_probate": meta["added_probate"],
                "corrected_raw_probate": cr.get("probate") if meta["added_probate"] else None,
            })

    # ---- report -------------------------------------------------------------------
    print("\n=== Greenville County SC raw['distressed']=True correction: DRY-RUN REPORT ===")
    print(f"Genuinely affected rows (strict bug signature): {strict_true:,}")
    print(f"Parcel groups touched: {stats['parcels_affected']:,}")
    print(f"  of those groups:")
    print(f"    tier DOWNGRADE : {stats['parcels_downgrade']:,}")
    for k in sorted(stats):
        if k.startswith("downgrade:"):
            print(f"        {k.split(':', 1)[1]:>12}: {stats[k]:,}")
    print(f"    tier NO CHANGE : {stats['parcels_no_change']:,}")
    print(f"    tier UPGRADE   : {stats['parcels_upgrade']:,}  "
          f"(only possible via the probate side-effect add, see below)")
    for k in sorted(stats):
        if k.startswith("upgrade:"):
            print(f"        {k.split(':', 1)[1]:>12}: {stats[k]:,}")

    print(f"\nProbate side-effect status across the {stats['rows_affected']:,} affected rows:")
    for k, v in sorted(probate_status_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {v:7,d}  {k}")

    collide = sum(1 for r in patch_rows if r["key_collision"])
    no_key = sum(1 for r in patch_rows if r["key"] is None)
    print(f"\nWhole-board dedupe_key() collision guard:")
    print(f"  safely patchable (unique key board-wide): {len(patch_rows) - collide - no_key:,}")
    print(f"  SKIPPED -- key collides elsewhere on the board: {collide:,}")
    print(f"  SKIPPED -- row could not be keyed at all: {no_key:,}")

    if mismatches:
        print(f"\nWARNING: {len(mismatches):,} row(s) where the recomputed CURRENT tier "
              f"disagrees with the tier already published on the board. First 5:")
        for src, pid, pub, recomputed in mismatches[:5]:
            print(f"  source={src!r} parcel={pid!r} published={pub!r} recomputed={recomputed!r}")
        print("  (Recomputed values are still used for the before/after comparison above; "
              "a published/recomputed mismatch means the live tier may reflect inputs -- "
              "e.g. equity/comps enrichment -- this script's lighter Listing reconstruction "
              "does not fully replay. Investigate before trusting --execute on these rows.)")
    else:
        print("\nSanity check: recomputed CURRENT tier matches the tier already published "
              "on the board for every affected row with a published distress_stack.")

    if args.limit:
        patch_rows = patch_rows[:args.limit]

    if not args.execute:
        print("\nDRY RUN -- nothing written. Re-run with --execute (and "
              "BOARD_PATCH_ALLOW_LARGE=1) to apply.")
        return 0

    # ---- execute (not exercised by the dry-run session that wrote this script) -----
    now_iso = datetime.now(timezone.utc).isoformat()
    patches: dict[str, dict] = {}
    skipped_unsafe = 0
    for row in patch_rows:
        if row["key"] is None or row["key_collision"]:
            skipped_unsafe += 1
            continue
        raw_patch: dict = {
            "distressed": None,
            "greenville_distress_correction": {
                "ts": now_iso, "fix_commit": _FIX_COMMIT,
                "removed_fake_property_signal": "distressed_condition (PROPERTY, weight 8)",
                "probate_status": row["probate_status"],
                "tier_before": row["tier_before"], "tier_after": row["tier_after"],
            },
        }
        if row["added_probate"]:
            raw_patch["probate"] = row["corrected_raw_probate"]
        patches[row["key"]] = {"raw": raw_patch}

    print(f"\n[{time.strftime('%H:%M:%S')}] applying {len(patches):,} patches "
          f"({skipped_unsafe:,} skipped as unsafe to key) ...", flush=True)
    try:
        with board_lock(REPO, owner="backfill_greenville_distress_correction"):
            result = patch_existing_rows(
                patches,
                {"backfill_greenville_distress_correction": f"{len(patches)} rows"},
                docs_dir=docs)
    except BoardLockBusy as exc:
        print(f"{exc} -- another board writer is active. Nothing written.", flush=True)
        return 1
    print("=== patch_existing_rows result ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
    print("\nNOTE: this does not re-run distress_score.score_board() over the whole board, "
          "so the patched rows' OWN raw['distress_stack'] still shows the pre-correction "
          "tier until the next full scoring pass (scripts/patch_distress_score.py) runs. "
          "The raw['distressed']/raw['probate'] correction is what matters for that NEXT "
          "scoring pass to compute the right tier; this script intentionally does not try "
          "to hand-patch distress_stack itself (that is scoring's job, not this backfill's).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
