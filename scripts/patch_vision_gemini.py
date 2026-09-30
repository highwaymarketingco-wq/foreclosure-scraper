"""Fast re-Vision patch: apply Gemini Vision to the CURRENT board without
re-running the full pipeline, then recompute calc + grade for the leads it
actually touched.

Use when the scraped/enriched data is fresh but Vision needs (re)running on a
different provider/config. Honors VISION_PROVIDER / VISION_MAX_LISTINGS /
VISION_INTER_CALL_DELAY from the env (run_local.sh-style). Gemini runs one
parallel stream per key.

  GEMINI_API_KEY_1=.. GEMINI_API_KEY_2=.. VISION_PROVIDER=gemini \
    VISION_MAX_LISTINGS=800 uv run python scripts/patch_vision_gemini.py

BOARD I/O REWRITE (2026-09-30, same pattern as resolver_backfill_parcel.py's/
resolver_backfill_geocode.py's 2026-09-29 rewrites and
recompute_geo_imprecise_confidence.py's 2026-09-30 targeted-patch shape):
this used to call load_board() to build the WHOLE board (217K+ rows) as
`listings`, run vision + recompute calc/grade "onto every lead" (the vast
majority of which vision never touches), then write_artifact(listings, ...) —
the whole board re-validated and re-serialized to land what one run actually
changes (up to VISION_MAX_LISTINGS, historically far fewer once the photo
filter and wall-clock budget apply). That is exactly the double
materialization BOARD_LOAD_MAX_SOURCE_MB / read_board_records() now refuse on
this board's real size (2,651+ MB, over the 1,200 MB ceiling) -- this script
was, in practice, BLOCKED, failing every scheduled 09:30 run since 2026-09-30.

THE ACTUAL TARGET POPULATION IS SMALL, EVEN THOUGH "un-scored" ISN'T.
needs_vision() (daily-incremental: no vision yet, OR only a low-quality
ollama-provider vision) has historically matched ~150K-190K of ~217K rows --
nearly the whole board, because most rows were scraped without ever getting a
Vision pass. But enrich_with_vision() ITSELF immediately re-filters that down
to rows with a usable photo (`_has_real_image`) before doing anything else,
UNLESS VISION_INCLUDE_NO_PHOTO=1 -- and historically that survivor set is
~4,500-5,000 rows, not ~190K (see e.g. 2026-09-26's log: 190,903 un-scored, of
which only 4,884 had a photo). A basemap-only row can only ever return a null
condition_tier, so it was never useful cargo for enrich_with_vision() to carry
around -- it was only IN the old `unscored` list because load_board() had
already paid to materialize the whole board anyway.

So: this streams the board WITH the lazy-detail sidecar merged
(web_artifact._iter_board_records -- "vision" is a LAZY_DETAIL_KEY, so a
plain slim read would see zero vision reports and re-grade the same head of
the list forever, exactly as the old docstring warned), and for each row does
a CHEAP dict/light-Listing check (needs_vision, then _has_real_image) before
ever calling Listing.model_validate() -- only the (bounded, historically
~4,500-row) survivor set is ever fully validated into a real Listing.
VISION_INCLUDE_NO_PHOTO=1 is the one config this streaming rewrite does NOT
support (it would require materializing the full ~190K-row "un-scored" set,
the exact cost this rewrite exists to avoid) -- it is refused outright with a
clear message rather than silently processing a truncated set.

enrich_with_vision(candidates, max_listings=cap) itself is UNCHANGED -- same
call, same internal filtering/sorting/capping/circuit-breaker. After it
returns, calc/grade are recomputed (calc.compute()/grading.grade() are pure
per-row functions of one Listing's own raw dict, confirmed by
recompute_geo_imprecise_confidence.py's own investigation) ONLY for the
candidates this run's vision pass actually touched (detected by object-
identity: _apply()/_record_ungraded() always assign a NEW dict to
li.raw["vision"]/li.raw["vision_unscored"], never mutate the old one in
place) -- not "every lead" as before, which was a no-op for ~216K+ rows every
single run. Every touched row's changed raw keys (vision, vision_unscored,
condition_tier, condition_source, calc, grade) land in ONE
web_artifact.patch_existing_rows() call.

DISCLOSED GAP: patch_existing_rows()'s raw update MERGES keys in, it cannot
DELETE one -- so a stale raw["vision_fetch_failed"] marker that _apply()
pops on a fresh score (cosmetic bookkeeping only; _needs_vision() already
short-circuits on raw["vision"] before ever consulting that marker, per its
own docstring) is not cleared by this script's patch. Functionally inert,
unlike the fields above.

BOARD I/O CONTRACT (do not regress):
  read  -> web_artifact._iter_board_records(), which merges the lazy-detail
           sidecar (docs/listings_detail.json) back into each row's raw AS IT
           STREAMS, never holding the whole board in memory at once.
  write -> web_artifact.patch_existing_rows(), which mutates only the rows
           this run's vision pass actually touched, streaming everything else
           through unchanged. Never write listings.json by hand -- it silently
           wipes the sidecar.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.models import Listing  # noqa: E402
from foreclosure_scraper.enrichment_vision import (  # noqa: E402
    _distress_tier, _has_real_image, enrich_with_vision, vision_max_seconds,
)
from foreclosure_scraper.valuation import calc as valuation_calc  # noqa: E402
from foreclosure_scraper.valuation import grading as valuation_grading  # noqa: E402
from foreclosure_scraper.publish import board_seal_pathspec  # noqa: E402
from foreclosure_scraper.web_artifact import (  # noqa: E402
    BoardLockBusy, _iter_board_records, board_lock, patch_existing_rows,
)
from foreclosure_scraper.publish import manifest_pathspec, push_deferred, push_with_retries  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

#: raw keys a vision + recompute pass can possibly touch -- anything else on a
#: candidate's raw is left exactly as it streamed in (patch_existing_rows()
#: merges this subset into the row's existing raw, never replaces it).
_PATCHABLE_RAW_KEYS = ("vision", "vision_unscored", "condition_tier", "condition_source",
                       "calc", "grade")


def needs_vision(li: Listing) -> bool:
    """Daily-incremental target test: score listings that DON'T already have
    vision — PLUS ones only scored by the local Ollama floor (low quality), so a
    real provider upgrades them once fresh API quota is available. Unchanged from
    the pre-rewrite version; only correct when `li.raw` carries the merged
    lazy-detail sidecar (vision lives there), which _iter_board_records() guarantees.
    """
    vis = (li.raw or {}).get("vision")
    if not vis:
        return True
    return vis.get("_provider") == "ollama"


def _collect_candidates(docs: Path):
    """Stream the board WITH the lazy-detail sidecar merged, and return
    (candidates, total_rows, unscored_total) where `candidates` are the (bounded)
    real Listings this run might actually vision-score: needs_vision() AND a usable
    photo (_has_real_image). Only these are ever fully Listing.model_validate()'d;
    every other row is discarded the moment the cheap checks rule it out.
    """
    candidates: list[Listing] = []
    total_rows = 0
    unscored_total = 0
    for rec in _iter_board_records(docs):
        total_rows += 1
        raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
        # cheap pre-check (no validation) before paying for a full Listing
        light = Listing.model_construct(raw=raw)
        if not needs_vision(light):
            continue
        unscored_total += 1
        if not _has_real_image(light):
            continue
        try:
            li = Listing.model_validate(rec)
        except Exception:  # noqa: BLE001 - a malformed row must not crash the whole pass
            continue
        candidates.append(li)
    return candidates, total_rows, unscored_total


def main() -> int:
    # THE LOCK, held across the streaming read -> vision -> patch -> publish.
    #
    # This was the longest-held board in the system: VISION_MAX_SECONDS used to
    # default to 14400 (4h; now 90 min, see enrichment_vision.vision_max_seconds),
    # so a board loaded at 09:33 was still being written back at 13:36. The
    # streaming rewrite does not change this lock-holding shape -- the lock still
    # covers the whole pass -- but the board no longer needs to be fully
    # materialized to do it.
    #
    # Reentrant: run_daily_vision.sh already holds this lock when it invokes
    # this script, and passes it down through FORECLOSURE_BOARD_LOCK_HELD.
    try:
        with board_lock(REPO, owner="patch_vision_gemini.py"):
            return asyncio.run(_run())
    except BoardLockBusy as exc:
        print(f"{exc} — skipping this vision pass.", flush=True)
        return 0


async def _run() -> int:
    if os.environ.get("VISION_INCLUDE_NO_PHOTO", "0") == "1":
        # That config needs enrich_with_vision() to see the FULL un-scored population
        # (historically ~150K-190K rows), which is the exact whole-board
        # materialization this rewrite exists to avoid. Refuse cleanly rather than
        # silently run a truncated (photo-only) pass under a flag that promised more.
        print("VISION_INCLUDE_NO_PHOTO=1 is not supported by this streaming pass "
              "(it needs the full un-scored population in memory -- the same cost "
              "load_board() refuses on this board's real size). Unset it, or run "
              "the legacy load_board()-based path deliberately with "
              "BOARD_LOAD_ALLOW_LARGE=1 if this is genuinely needed.", file=sys.stderr, flush=True)
        return 3

    candidates, total_rows, unscored_total = _collect_candidates(DOCS)
    already = total_rows - unscored_total
    n_hot = sum(1 for li in candidates if _distress_tier(li) == "HOT")
    n_warm = sum(1 for li in candidates if _distress_tier(li) == "WARM")
    print(f"[{time.strftime('%H:%M:%S')}] scanned {total_rows} board rows (sidecar merged) | "
          f"{already} already vision-scored; {unscored_total} un-scored, of which "
          f"{len(candidates)} have a photo ({n_hot} HOT, {n_warm} WARM). Running "
          f"{os.environ.get('VISION_PROVIDER','?')} vision (wall clock "
          f"{vision_max_seconds():.0f}s) on the photo rows, HOT then WARM first…", flush=True)

    cap = int(os.environ.get("VISION_MAX_LISTINGS", "800"))
    # Snapshot identity + "had vision" BEFORE the pass so the actually-touched subset
    # can be detected afterward by object-identity: _apply()/_record_ungraded() always
    # assign a NEW dict to raw["vision"]/raw["vision_unscored"], never mutate in place.
    before_vision_obj = {id(li): li.raw.get("vision") for li in candidates}
    before_had_vision = {id(li): bool(li.raw.get("vision")) for li in candidates}
    before_had_unscored = {id(li): ("vision_unscored" in li.raw) for li in candidates}

    t0 = time.time()
    _budget = vision_max_seconds()
    hard_cap = (_budget + 120) if _budget > 0 else None
    try:
        await asyncio.wait_for(
            enrich_with_vision(candidates, max_listings=cap), timeout=hard_cap)
    except asyncio.TimeoutError:
        print(f"[{time.strftime('%H:%M:%S')}] vision pass hit hard cap ({(hard_cap or 0):.0f}s) "
              f"— writing partial progress", flush=True)
    print(f"[{time.strftime('%H:%M:%S')}] vision pass done in {int(time.time()-t0)}s", flush=True)

    touched = [li for li in candidates
              if li.raw.get("vision") is not before_vision_obj[id(li)]
              or (("vision_unscored" in li.raw) and not before_had_unscored[id(li)])]

    # Recompute calc + grade (condition_tier may have changed) -- ONLY for rows this
    # run's vision pass actually touched. calc.compute()/grade.grade() are pure
    # functions of one Listing's own raw dict, so recomputing an untouched candidate
    # (or a row not in `candidates` at all) would be a byte-identical no-op; scoping
    # to `touched` just skips paying for that no-op instead of guaranteeing anything
    # different than the old "every lead" loop did.
    for li in touched:
        if not isinstance(li.raw, dict):
            li.raw = {}
        try:
            c = valuation_calc.compute(li)
            g = valuation_grading.grade(li, c)
            li.raw["calc"] = valuation_calc.to_dict(c)
            li.raw["grade"] = valuation_grading.to_dict(g)
        except Exception:  # noqa: BLE001
            pass

    newly_gained = sum(1 for li in touched
                       if not before_had_vision[id(li)] and li.raw.get("vision"))
    scored_now_estimate = already + newly_gained  # see module docstring: exact, not approximate

    pending_patches: dict[str, dict] = {}
    for li in touched:
        patch_raw = {k: li.raw[k] for k in _PATCHABLE_RAW_KEYS if k in li.raw}
        if not patch_raw:
            continue
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            continue
        pending_patches[key] = {"raw": patch_raw}

    print(f"[{time.strftime('%H:%M:%S')}] touched {len(touched)}/{len(candidates)} candidates "
          f"this run; {newly_gained} newly gained a vision report", flush=True)

    if not pending_patches:
        print(f"[{time.strftime('%H:%M:%S')}] nothing to patch this run", flush=True)
        return 0

    summary = {"notes": (f"daily vision pass: {scored_now_estimate} of {total_rows} listings "
                         f"have a vision report (+{newly_gained} this run)")}
    stats = patch_existing_rows(pending_patches, summary, docs_dir=DOCS)
    print(f"[{time.strftime('%H:%M:%S')}] patched {stats['applied']}/{len(pending_patches)} rows "
          f"(existing board: {stats['existing']:,}) — vision now ≈{scored_now_estimate} "
          f"of {total_rows} listings", flush=True)

    # Publish to the GitHub Pages dashboard (docs/ doesn't touch workflows,
    # so the normal token can push it).
    if os.environ.get("PATCH_PUBLISH", "1") == "1":
        import subprocess
        root = str(REPO)
        try:
            # Commit only the .gz twins the dashboard fetches. The uncompressed
            # listings.json/.detail.json are gitignored (they exceed GitHub's
            # 100MB/file limit and Pages excludes them); load_board rebuilds from
            # the .gz. Naming a gitignored path in `git add` fails the whole add,
            # so it must NOT appear here.
            # listings_slim.json.gz is the mobile payload write_artifact() emits.
            # patch_existing_rows() does NOT regenerate it (disclosed gap, same as
            # append_new_rows()) -- it is appended ONLY IF IT EXISTS/tracked, same
            # gate as before, so a stale-but-present slim file still gets staged
            # (and carried forward unchanged) rather than silently dropped from the
            # commit.
            pub = [*board_seal_pathspec(root), "docs/listings_detail.json.gz",
                   "docs/run_meta.json"]
            if (DOCS / "listings_slim.json.gz").exists() or subprocess.run(
                    ["git", "ls-files", "--error-unmatch", "docs/listings_slim.json.gz"],
                    cwd=root, capture_output=True).returncode == 0:
                pub.append("docs/listings_slim.json.gz")
            if (DOCS / "detail_shards").is_dir() or subprocess.run(
                    ["git", "ls-files", "--error-unmatch", "docs/detail_shards"],
                    cwd=root, capture_output=True).returncode == 0:
                pub.append("docs/detail_shards")
            # the manifest seals the payload set: a commit that carries a new board must carry
            # the manifest that describes it (a stale one makes a gz-only reader refuse the board)
            pub += manifest_pathspec(root)
            subprocess.run(["git", "add", *pub], cwd=root, check=False)
            r = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=root)
            if r.returncode != 0:  # there are changes
                subprocess.run(["git", "commit", "-q", "-m",
                                f"daily vision: {newly_gained} listings scored ({time.strftime('%Y-%m-%d')})"],
                               cwd=root, check=False)
                if push_deferred():
                    # run_daily_vision.sh sets BOARD_PUSH_DEFERRED=1: it releases the board lock
                    # and pushes (scripts/publish_helper.sh), so a stalled push cannot hold the lock
                    print(f"[{time.strftime('%H:%M:%S')}] committed; push deferred to the wrapper "
                          f"(outside the board lock)", flush=True)
                else:
                    ok, tail = push_with_retries(root)
                    print(f"[{time.strftime('%H:%M:%S')}] "
                          + ("dashboard published ✓" if ok else f"PUBLISH_PUSH_FAILED: {tail}"), flush=True)
        except Exception as exc:
            print(f"publish error: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
