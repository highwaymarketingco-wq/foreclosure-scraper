"""Fast re-Vision patch: apply Gemini Vision to the CURRENT docs/listings.json
without re-running the full pipeline, then recompute calc + grade + rewrite.

Use when the scraped/enriched data is fresh but Vision needs (re)running on a
different provider/config. Honors VISION_PROVIDER / VISION_MAX_LISTINGS /
VISION_INTER_CALL_DELAY from the env (run_local.sh-style). Gemini runs one
parallel stream per key.

  GEMINI_API_KEY_1=.. GEMINI_API_KEY_2=.. VISION_PROVIDER=gemini \
    VISION_MAX_LISTINGS=800 uv run python scripts/patch_vision_gemini.py

BOARD I/O CONTRACT (do not regress):
  read  -> web_artifact.load_board(), which merges the lazy-detail sidecar
           (docs/listings_detail.json) back into each lead's raw. "vision" is a
           LAZY_DETAIL_KEY, so a plain json.loads of the slim listings.json sees
           ZERO vision reports and this pass re-grades the same head of the list
           every single day instead of advancing coverage.
  write -> web_artifact.write_artifact(), which re-splits the sidecar and emits
           the .gz twins. Hand-writing listings.json silently wipes the sidecar.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_vision import enrich_with_vision
from foreclosure_scraper.valuation import calc as valuation_calc
from foreclosure_scraper.valuation import grading as valuation_grading
from foreclosure_scraper.web_artifact import (
    BoardLockBusy, board_lock, load_board, read_board_records, write_artifact,
)

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _hydrate(d: dict) -> Listing | None:
    """Lenient record -> Listing. Drops unknown keys and coerces the two enum
    fields, so a record that strict Listing.model_validate rejects can still be
    recovered instead of being dropped from the published board."""
    fields = {k: v for k, v in d.items() if k in Listing.model_fields}
    if isinstance(fields.get("listing_type"), str):
        try:
            fields["listing_type"] = ListingType(fields["listing_type"])
        except ValueError:
            fields.pop("listing_type", None)
    if isinstance(fields.get("property_kind"), str):
        try:
            fields["property_kind"] = PropertyKind(fields["property_kind"])
        except ValueError:
            fields.pop("property_kind", None)
    try:
        li = Listing.model_validate(fields)
    except Exception:
        return None
    li.raw = d.get("raw") or {}
    return li


def load_board_no_shrink(docs: Path | str = DOCS) -> tuple[list[Listing], int]:
    """load_board() plus a hard never-shrink guarantee.

    load_board() silently skips any record that fails Listing.model_validate.
    Publishing a board with fewer leads than it had is a far worse bug than the
    stale-coverage one this script exists to fix, so when the counts disagree we
    re-load every record through the lenient hydrator and keep the strays.

    Returns (listings, n_records_on_disk) so the caller can hard-guard the write.

    The record count and the recovery pass both come from read_board_records(),
    which is load_board()'s own sidecar merge without the validation step — so
    the two can no longer disagree about what "the board" is, and both work from
    the committed .gz on a checkout where the uncompressed twin (gitignored,
    >100MB) is absent. A local copy of that merge used to live here and read
    docs/listings.json unconditionally.
    """
    docs = Path(docs)
    records = read_board_records(docs)
    n_records = len(records)
    board = load_board(docs)
    if len(board) == n_records:
        return board, n_records
    print(f"[{time.strftime('%H:%M:%S')}] load_board dropped "
          f"{n_records - len(board)} invalid record(s) — recovering them leniently "
          f"so the published board cannot shrink", flush=True)
    recovered: list[Listing] = []
    for rec in records:
        try:
            recovered.append(Listing.model_validate(rec))
            continue
        except Exception:  # noqa: BLE001
            pass
        li = _hydrate(rec)
        if li is not None:
            recovered.append(li)
    return recovered, n_records


def needs_vision(li: Listing) -> bool:
    """Daily-incremental target test: score listings that DON'T already have
    vision — PLUS ones only scored by the local Ollama floor (low quality), so a
    real provider upgrades them once fresh API quota is available. Each run thus
    advances coverage AND quality over the week as free quotas reset.

    Only correct when `li` came through load_board(): vision lives in the lazy
    sidecar, so a listing hydrated from the slim listings.json always looks
    un-scored.
    """
    vis = (li.raw or {}).get("vision")
    if not vis:
        return True
    return vis.get("_provider") == "ollama"


async def main() -> int:
    # THE LOCK, held across load_board -> vision -> write_artifact -> publish.
    #
    # This is the longest-held board in the system: VISION_MAX_SECONDS defaults
    # to 14400 (4h), so a board loaded at 09:33 is still being written back at
    # 13:36 — straight over the noon lrcpwa pass and the 2pm SOS pass, both of
    # which had already published. On 2026-08-10 that reverted 1,064 resolved
    # parcels, 343 county values and 410 absentee tags, and nothing errored.
    #
    # Reentrant: run_daily_vision.sh already holds this lock when it invokes
    # this script, and passes it down through FORECLOSURE_BOARD_LOCK_HELD.
    try:
        with board_lock(Path(__file__).resolve().parent.parent,
                        owner="patch_vision_gemini.py"):
            return await _run()
    except BoardLockBusy as exc:
        print(f"{exc} — skipping this vision pass.", flush=True)
        return 0


async def _run() -> int:
    # Read through load_board so the lazy-detail sidecar (vision/comps/cama) is
    # merged into raw BEFORE needs_vision() runs — otherwise every lead looks
    # un-scored and the pass re-grades the same head of the list forever.
    listings, n_records = load_board_no_shrink(DOCS)
    print(f"[{time.strftime('%H:%M:%S')}] loaded {len(listings)} listings "
          f"({n_records} records on disk, lazy-detail sidecar merged)", flush=True)

    cap = int(os.environ.get("VISION_MAX_LISTINGS", "800"))
    unscored = [li for li in listings if needs_vision(li)]
    already = len(listings) - len(unscored)
    print(f"[{time.strftime('%H:%M:%S')}] {already} already vision-scored; "
          f"{len(unscored)} un-scored. Running {os.environ.get('VISION_PROVIDER','?')} "
          f"vision (cap {cap}) on the un-scored, prioritized…", flush=True)
    t0 = time.time()
    # Hard wall-clock cap: a single hung worker (stuck network await) must NOT
    # stall the whole run forever. enrich_with_vision applies results to each
    # listing in place as it goes, so on timeout we still keep partial progress
    # and proceed to write/publish what was scored. Default 4h; +120s grace so
    # the pool's own internal VISION_MAX_SECONDS deadline fires first when set.
    hard_cap = float(os.environ.get("VISION_MAX_SECONDS", "14400")) + 120
    try:
        await asyncio.wait_for(
            enrich_with_vision(unscored, max_listings=cap), timeout=hard_cap)
    except asyncio.TimeoutError:
        print(f"[{time.strftime('%H:%M:%S')}] vision pass hit hard cap ({hard_cap:.0f}s) "
              f"— writing partial progress", flush=True)
    print(f"[{time.strftime('%H:%M:%S')}] vision pass done in {int(time.time()-t0)}s", flush=True)

    # Recompute calc + grade (condition_tier may have changed) onto every lead.
    scored = 0
    for li in listings:
        try:
            c = valuation_calc.compute(li)
            g = valuation_grading.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = valuation_calc.to_dict(c)
            li.raw["grade"] = valuation_grading.to_dict(g)
        except Exception:
            pass
        if (li.raw or {}).get("vision"):
            scored += 1

    # Never publish a shrunken board. If anything above lost leads, bail BEFORE
    # the write — a stale board beats a truncated one.
    if len(listings) < n_records:
        print(f"[{time.strftime('%H:%M:%S')}] ABORT: would publish {len(listings)} of "
              f"{n_records} records — refusing to shrink the board", flush=True)
        return 2

    # PASS ONLY WHAT THIS RUN ACTUALLY COMPUTED.
    #
    # _prior_meta() used to live here: it read the prior docs/run_meta.json and
    # handed by_source / by_state / source_status / regressions / errors straight
    # back as this pass's summary. That looks like preservation and is actually
    # laundering — write_artifact stamps health_carried_from /
    # health_carried_keys ONLY when a key is ABSENT from the summary it is
    # handed, so re-supplying them made the carry-forward branch dead code and
    # the published file asserted a months-old per-source health report as
    # current, unlabelled. Measured on the live board: by_state summed 36,060
    # against a 38,500 board (2,440 leads, 6.3%, unaccounted) and no
    # health_carried_from appeared anywhere in the file.
    #
    # write_artifact carries the same values forward from the same file and
    # labels them; by_state and by_source_on_board it derives from the board
    # being written, so those come out current instead of carried.
    summary = {"notes": (f"daily vision pass: {scored} of {len(listings)} listings "
                         f"have a vision report")}
    write_artifact(listings, summary, docs_dir=DOCS)
    print(f"[{time.strftime('%H:%M:%S')}] wrote {DOCS/'listings.json'} + sidecar — "
          f"{len(listings)} listings, {scored} total now have vision", flush=True)

    # Publish to the GitHub Pages dashboard (docs/ doesn't touch workflows,
    # so the normal token can push it).
    if os.environ.get("PATCH_PUBLISH", "1") == "1":
        import subprocess
        root = str(Path(__file__).parent.parent)
        try:
            # Commit only the .gz twins the dashboard fetches. The uncompressed
            # listings.json/.detail.json are gitignored (they exceed GitHub's
            # 100MB/file limit and Pages excludes them); load_board rebuilds from
            # the .gz. Naming a gitignored path in `git add` fails the whole add,
            # so it must NOT appear here.
            # listings_slim.json.gz is the mobile payload write_artifact() emits.
            # It is appended ONLY IF IT EXISTS: a pathspec matching no file makes
            # `git add` exit 128 and stage NOTHING AT ALL, which would silently
            # stop publishing the dashboard entirely on a checkout where the slim
            # emitter has not run yet.
            pub = ["docs/listings.json.gz", "docs/listings_detail.json.gz",
                   "docs/run_meta.json"]
            # ...but "exists" alone is the wrong gate once it IS tracked: the
            # emitter deletes both slim files if projection fails, and that
            # DELETION has to be staged or phones keep being served the last
            # published slim beside a board that has moved on. The 128-exit only
            # fires when the path is absent AND untracked, so test for both.
            if (DOCS / "listings_slim.json.gz").exists() or subprocess.run(
                    ["git", "ls-files", "--error-unmatch", "docs/listings_slim.json.gz"],
                    cwd=root, capture_output=True).returncode == 0:
                pub.append("docs/listings_slim.json.gz")
            # docs/detail_shards/ is the per-lead detail payload phones fetch,
            # emitted by the same write_artifact() call. Same gate, same reasons
            # — a DIRECTORY pathspec behaves identically: absent AND untracked
            # exits 128 and stages nothing, while `git add <dir>` on a tracked
            # directory stages deletions inside it, which is how the emitter's
            # remove-the-directory failure path reaches the live site.
            if (DOCS / "detail_shards").is_dir() or subprocess.run(
                    ["git", "ls-files", "--error-unmatch", "docs/detail_shards"],
                    cwd=root, capture_output=True).returncode == 0:
                pub.append("docs/detail_shards")
            subprocess.run(["git", "add", *pub], cwd=root, check=False)
            r = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=root)
            if r.returncode != 0:  # there are changes
                subprocess.run(["git", "commit", "-q", "-m",
                                f"daily vision: {scored} listings scored ({time.strftime('%Y-%m-%d')})"],
                               cwd=root, check=False)
                subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"],
                               cwd=root, check=False)
                p = subprocess.run(["git", "push", "origin", "main"], cwd=root)
                print(f"[{time.strftime('%H:%M:%S')}] "
                      + ("dashboard published ✓" if p.returncode == 0 else "push failed ⚠"), flush=True)
        except Exception as exc:
            print(f"publish error: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
