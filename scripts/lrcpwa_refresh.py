"""Scheduled land-records refresh — fills the lrcpwa addresses + assessed values
+ absentee flags + county building PHOTOS that were deferred when the
lrcpwa.ncptscloud.com API rate-limited during heavy same-day testing, then
recomputes the strategy + buyer-match tags (board-wide) and calc/grade (board-
wide, same as the original). Runs on the committed board (no re-scrape); the
shell wrapper commits + pushes.

Board-writer — the wrapper guards against running while the weekly/merge is
active. Safe + idempotent: lrcpwa skips leads that already have an address,
photos skip files already on disk.

BOARD I/O REWRITE (2026-10-01, same pattern as sos_agent_refresh.py's/
patch_vision_gemini.py's 2026-09-30 rewrites and _dq_common.run_apply()'s
2026-10-01 rewrite): this used to call load_board() to build the WHOLE board
as `listings`, mutate lrcpwa/strategy_fit/buyer_match/calc/grade on it, then
write_artifact(listings, ...) — the whole ~212K-row board re-validated and
re-serialized every single day. That is exactly the double materialization
BOARD_LOAD_MAX_SOURCE_MB now refuses on this board's real size (2,646+ MB,
over the 1,200 MB ceiling — confirmed via the 2026-10-01 12:00:03 log entry):
this script was, in practice, BLOCKED, failing fast/safe with BoardLoadTooLarge
every scheduled noon run since the board crossed the ceiling.

CLASSIFICATION (traced through every enricher this script calls, not assumed):
enrich_lrcpwa_parcel() / enrich_lrcpwa_photo() (enrichment_lrcpwa_parcel.py /
enrichment_lrcpwa_photo.py) are bounded, per-row, network-bound passes — each
builds its OWN small `targets` list (a county in the NC land-records cluster,
a parcel_id, missing the specific field it fills) and caps it
(LRCPWA_MAX/LRCPWA_PHOTO_MAX, default 6000; historically ~2,772/~3,849 of
~212K rows). enrich_strategy_fit() / enrich_buyer_match()
(enrichment_strategy_fit.py / enrichment_buyer_match.py) and
valuation.calc.compute()/valuation.grading.grade() are, by contrast, run over
EVERY row in the original (not just lrcpwa's own targets) — but every one of
them is a PURE PER-ROW function of that one Listing's own (sidecar-merged) raw
dict: no board-wide aggregation, grouping, or percentile tiering (confirmed by
reading all four modules in full and grepping valuation/calc.py +
valuation/grading.py for any `listings`-wide loop — COUNTY_MEDIAN_PPSF and
friends are static tables, not computed live from the board). That is
DIFFERENT from a genuinely whole-board operation like dedupe()/
distress_score.score_board() (daily_api_refresh.py's case, correctly left
unmigrated): "evaluated against every row" is a large POPULATION, not a
cross-row DEPENDENCY, so it streams fine — process one row, emit its patch (if
anything changed), discard it, move on — never holding more than one row (plus
the small lrcpwa-touched set) in memory at once. This is actually a TIGHTER
memory profile than _dq_common.run_apply()'s _light_rows() (which must hold
the whole working set in memory because ITS callers need repeated/random
access across rows — this script's callers do not).

HOW, CONCRETELY. One streaming pass over web_artifact._iter_board_records()
(the lazy-detail sidecar MUST be merged — calc.compute() reads
raw['vision']/raw['cama']/raw['comps'], all LAZY_DETAIL_KEYS, exactly the
hazard patch_vision_gemini.py's own docstring warns about; a plain
board_stream.iter_board_rows() slim read would silently impoverish every
recomputed calc/grade):

  1. For each record, a cheap dict-level pre-check (_is_parcel_target /
     _is_photo_target, via a light Listing.model_construct() of just the
     relevant fields — reusing enrichment_lrcpwa_parcel._county() /
     enrichment_lrcpwa_photo._worth_photo()/_has_image() directly rather than
     duplicating their logic) decides, before ever fully validating the row,
     whether it is an lrcpwa target this run (bounded by the SAME
     LRCPWA_MAX/LRCPWA_PHOTO_MAX caps those modules themselves apply, so a
     future expansion of TENANTS cannot make this collection unbounded).
  2. A target's dedupe_key() and a deep snapshot of its pre-mutation state are
     captured BEFORE any enrichment touches it and stashed in `parcel_targets`/
     `photo_targets` — required because _apply() FILLS street_address and
     zip_code, both identity fields Listing.dedupe_key() reads, on exactly the
     rows targeted (they are targets precisely because street_address was
     blank). This is the same pre/post-mutation identity hazard
     resolver_backfill_parcel.py's parcel_id case documents, handled the same
     way: key captured first, used for the eventual patch regardless of what
     the row's identity becomes afterward. (In practice every lrcpwa target
     also carries a parcel_id, so Listing.dedupe_key()'s strongest branch is
     used either way and the key does not actually shift — this capture is
     still done unconditionally, the safe-by-construction default, not a
     targeted exception for the cases observed to need it.)
  3. A row that is NOT an lrcpwa target this run is finished immediately,
     right there in the loop: calc/grade recomputed, strategy_fit/buyer_match
     (re)tagged, diffed against its own pre-mutation snapshot, and (if
     anything changed) added to the patch dict — then the Listing is dropped.
     This is the vast majority of the board (~208K of ~212K rows), and it
     never needs more than one row alive at a time.
  4. enrich_lrcpwa_parcel(parcel_targets) then enrich_lrcpwa_photo(photo_targets)
     run exactly as the original script ran them — same two REAL, UNCHANGED
     functions, same sequential order (so a row targeted by BOTH shares the
     same object, letting enrich_lrcpwa_photo's per-row `raw['lrcpwa']['id']`
     reuse skip enrich_lrcpwa_photo._resolve_id()'s network call exactly as it
     did before, since the targeting conditions for both never depend on
     anything the other one sets).
  5. Each touched target is THEN finished the same way step 3 does (calc/
     grade/strategy_fit/buyer_match), diffed against the per-row snapshot
     taken in step 2 (which captures the lrcpwa mutation AND the recompute in
     one combined patch), and landed in the same patch dict.
  6. ONE web_artifact.patch_existing_rows() call lands everything — ANY row
     calc/grade/strategy_fit/buyer_match/lrcpwa actually changed, board-wide,
     not just lrcpwa's own bounded targets. patch_existing_rows() itself
     streams the existing board exactly once more to apply the patches (see
     its own docstring) — it does not require the patch set to be small, only
     that each individual patch value is (true here: small typed dicts, never
     a whole Listing).

DISCLOSED BEHAVIOR CHANGE (an improvement, not a regression — called out
explicitly rather than left for someone to discover later): a row that fails
Listing.model_validate() is no longer silently DELETED from the board on the
next write (load_board() drops it from the list it returns; write_artifact()
then writes the board back without it). A patch-based write cannot delete
anything it does not target: a malformed row simply does not get this run's
calc/grade/strategy_fit/buyer_match update and is otherwise left exactly as it
was. Dropped rows are counted and printed, not hard-failed on, since the
catastrophic case load_board()'s BoardLoadDropError guards against (writing
the board back minus the dropped rows) cannot happen here.

RAW_KEEP already covers every key this script writes (lrcpwa, images, zillow,
calc, grade, strategy_fit, buyer_match — verified by reading web_artifact.py's
RAW_KEEP dict directly, not assumed), so there is no silent-drop-on-next-
full-rewrite risk the way a brand-new, unregistered key would have.

This is the job that got reverted on 2026-08-10: 1,064 parcels resolved,
343 county values, 410 absentee tags, published — and then overwritten by
the 09:30 vision job writing back the board it had loaded at 09:33. The board
lock below is what actually fixed that (board_lock.sh's TOCTOU-racy pgrep
check was the old guard); this rewrite does not change that contract.
"""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path

from foreclosure_scraper.models import Listing
from foreclosure_scraper.enrichment_lrcpwa_parcel import (
    enrich_lrcpwa_parcel, _county, _MAX as _PARCEL_MAX,
)
from foreclosure_scraper.enrichment_lrcpwa_photo import (
    enrich_lrcpwa_photo, _worth_photo, _has_image, _MAX as _PHOTO_MAX,
)
from foreclosure_scraper.enrichment_strategy_fit import enrich_strategy_fit
from foreclosure_scraper.enrichment_buyer_match import enrich_buyer_match
from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade
from foreclosure_scraper.web_artifact import (
    BoardLockBusy, _iter_board_records, board_lock, patch_existing_rows,
)

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

#: light Listing fields needed by the cheap pre-checks below (_county/_worth_photo/_has_image)
#: and by dedupe_key() -- NOT a full Listing.model_validate(), so this is safe to build for
#: every row on the board without paying validation cost for the ~208K that aren't targets.
_LIGHT_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code",
                 "case_number", "source_url", "listing_type", "raw")


def _light(rec: dict) -> Listing:
    return Listing.model_construct(**{k: rec.get(k) for k in _LIGHT_FIELDS})


def _is_parcel_target(rec: dict) -> bool:
    """Mirrors enrichment_lrcpwa_parcel.enrich_lrcpwa_parcel()'s own targets filter exactly,
    reusing its real _county() rather than duplicating the TENANTS/state logic."""
    li = _light(rec)
    return bool(_county(li)) and bool((li.parcel_id or "").strip()) and not (li.street_address or "").strip()


def _is_photo_target(rec: dict) -> bool:
    """Mirrors enrichment_lrcpwa_photo.enrich_lrcpwa_photo()'s own targets filter exactly,
    reusing its real _county()/_has_image()/_worth_photo()."""
    li = _light(rec)
    return (bool(_county(li)) and bool((li.parcel_id or "").strip())
            and not _has_image(li) and _worth_photo(li))


def _finish_row(li: Listing) -> None:
    """Recompute calc/grade, then (re)tag strategy_fit/buyer_match -- the same four calls the
    original script made over its whole in-memory `listings` list, invoked here per-row. All
    four are pure functions of this ONE Listing's own (sidecar-merged) raw dict; see this
    module's docstring for how that was verified. Mutates `li` in place."""
    if not isinstance(li.raw, dict):
        li.raw = {}
    try:
        c = vcalc.compute(li)
        g = vgrade.grade(li, c)
        li.raw["calc"] = vcalc.to_dict(c)
        li.raw["grade"] = vgrade.to_dict(g)
    except Exception:  # noqa: BLE001 - matches the original script's own bare except here
        pass
    enrich_strategy_fit([li])
    enrich_buyer_match([li])


def _accumulate_tag_stats(li: Listing, strategy_counts: dict, buyer_counts: dict) -> None:
    """Board-wide strategy_fit/buyer_match totals, reproducing enrich_strategy_fit()'s/
    enrich_buyer_match()'s own stats shape exactly (every row currently carrying tags counts,
    not just rows that changed this run) -- needed because this script now calls them once per
    row instead of once over the whole list, so nothing else accumulates these totals."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    sf = raw.get("strategy_fit")
    if isinstance(sf, dict) and sf.get("tags"):
        strategy_counts["tagged"] += 1
        for t in sf["tags"]:
            strategy_counts["by_tag"][t] = strategy_counts["by_tag"].get(t, 0) + 1
    bm = raw.get("buyer_match")
    if isinstance(bm, dict) and bm.get("by_type"):
        buyer_counts["matched"] += 1
        cat = bm.get("category")
        if cat:
            buyer_counts["by_category"][cat] = buyer_counts["by_category"].get(cat, 0) + 1


def _diff_raw(before: dict | None, after: dict | None) -> dict:
    """{raw sub-key: new value} for every key this pass added or changed. A plain add/change
    diff is safe here (no delete-as-None case to represent, unlike _dq_common._diff_raw()'s
    callers): verified by reading enrichment_lrcpwa_parcel.py, enrichment_lrcpwa_photo.py,
    enrichment_strategy_fit.py, enrichment_buyer_match.py, valuation/calc.py and
    valuation/grading.py in full -- none of them ever pops or deletes a raw key, only ever
    `raw[k] = <value>`."""
    before = before or {}
    after = after or {}
    return {k: v for k, v in after.items() if before.get(k) != v}


def _diff_row(li: Listing, before_scalars: dict, before_raw: dict | None) -> dict | None:
    """Build patch_existing_rows()'s per-row update dict from a pre-mutation snapshot, or None
    if nothing changed."""
    update: dict = {}
    after_scalars = li.model_dump(mode="json", exclude={"raw"})
    for k, v in after_scalars.items():
        if before_scalars.get(k) != v:
            update[k] = v
    raw_update = _diff_raw(before_raw, li.raw if isinstance(li.raw, dict) else None)
    if raw_update:
        update["raw"] = raw_update
    return update or None


def main() -> int:
    # THE LOCK, held across the streaming read -> lrcpwa enrichment -> recompute -> patch.
    #
    # Reentrant: scripts/lrcpwa_refresh.sh already holds it when it invokes this
    # script and passes it down through FORECLOSURE_BOARD_LOCK_HELD, so this
    # acquire is a no-op there. It matters when the pass is run by hand.
    #
    # This is the job that got reverted on 2026-08-10: 1,064 parcels resolved,
    # 343 county values, 410 absentee tags, published — and then overwritten by
    # the 09:30 vision job writing back the board it had loaded at 09:33.
    try:
        with board_lock(REPO, owner="lrcpwa_refresh.py"):
            return _run()
    except BoardLockBusy as exc:
        print(f"{exc} — skipping this pass.", flush=True)
        return 0


def _run() -> int:
    patches: dict[str, dict] = {}
    strategy_counts = {"tagged": 0, "by_tag": {}}
    buyer_counts = {"matched": 0, "by_category": {}}
    parcel_targets: list[Listing] = []
    photo_targets: list[Listing] = []
    pre_keys: dict[int, str] = {}
    before_touched: dict[int, tuple[dict, dict | None]] = {}
    stream_total = 0
    total_rows = 0      # post-validation, matches the original's len(listings)
    dropped = 0
    b_addr = 0
    photos_before = 0

    for rec in _iter_board_records(DOCS):
        stream_total += 1
        want_parcel = len(parcel_targets) < _PARCEL_MAX and _is_parcel_target(rec)
        want_photo = len(photo_targets) < _PHOTO_MAX and _is_photo_target(rec)
        try:
            li = Listing.model_validate(rec)
        except Exception:  # noqa: BLE001 - a malformed row must not crash the whole pass
            dropped += 1
            continue
        total_rows += 1
        if (li.street_address or "").strip():
            b_addr += 1
        if isinstance(li.raw, dict) and (li.raw.get("images") or {}).get("real"):
            photos_before += 1

        if want_parcel or want_photo:
            try:
                key = li.dedupe_key()
            except Exception:  # noqa: BLE001 - a row too malformed to key is simply unpatchable
                continue
            pre_keys[id(li)] = key
            before_touched[id(li)] = (
                li.model_dump(mode="json", exclude={"raw"}),
                copy.deepcopy(li.raw) if isinstance(li.raw, dict) else None,
            )
            if want_parcel:
                parcel_targets.append(li)
            if want_photo:
                photo_targets.append(li)
            continue  # finished below, after lrcpwa enrichment runs on it

        # not an lrcpwa target this run -- finish it right here, one row alive at a time.
        before_scalars = li.model_dump(mode="json", exclude={"raw"})
        before_raw = copy.deepcopy(li.raw) if isinstance(li.raw, dict) else None
        _finish_row(li)
        _accumulate_tag_stats(li, strategy_counts, buyer_counts)
        update = _diff_row(li, before_scalars, before_raw)
        if update:
            try:
                key = li.dedupe_key()
            except Exception:  # noqa: BLE001
                continue
            patches[key] = update

    print(f"loaded {total_rows} | before addr={b_addr}"
          + (f" | dropped={dropped}" if dropped else ""), flush=True)

    async def go():
        ps = await enrich_lrcpwa_parcel(parcel_targets)
        phs = await enrich_lrcpwa_photo(photo_targets)
        return ps, phs
    parcel_stats, photo_stats = asyncio.run(go())
    print("lrcpwa_parcel:", parcel_stats, flush=True)
    print("lrcpwa_photo:", photo_stats, flush=True)

    # Finish the (bounded) lrcpwa-touched set: recompute value/grade on the leads lrcpwa just
    # valued, (re)tag strategy_fit/buyer_match, and diff against each one's PRE-lrcpwa snapshot
    # so lrcpwa's own field fills and this recompute land in one combined patch per row.
    touched: dict[int, Listing] = {}
    for li in parcel_targets:
        touched[id(li)] = li
    for li in photo_targets:
        touched[id(li)] = li
    for li in touched.values():
        before_scalars, before_raw = before_touched[id(li)]
        _finish_row(li)
        _accumulate_tag_stats(li, strategy_counts, buyer_counts)
        update = _diff_row(li, before_scalars, before_raw)
        if update:
            patches[pre_keys[id(li)]] = update

    print("strategy_fit:", strategy_counts, flush=True)
    print("buyer_match:", buyer_counts, flush=True)

    a_addr = b_addr + parcel_stats.get("address_filled", 0)
    photos_after = photos_before + photo_stats.get("fetched", 0) + photo_stats.get("cached", 0)

    if not patches:
        print(f"nothing to patch | addr={a_addr}(+{a_addr - b_addr}) real_photos={photos_after}",
              flush=True)
        return 0

    stats = patch_existing_rows(patches, {"notes": "scheduled land-records refresh"}, docs_dir=DOCS)
    print(f"wrote board | patched {stats['applied']}/{len(patches)} rows "
          f"(existing board: {stats['existing']:,}) | addr={a_addr}(+{a_addr - b_addr}) "
          f"real_photos={photos_after}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
