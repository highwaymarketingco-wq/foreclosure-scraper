"""Apply the stacked-distress score (HOT/WARM/COLD tiers) to docs/listings.json
and republish. Pure computation over existing signals -- no scraping.

MIGRATED 2026-10-01 (task_board_dedupe_stream) off read_board_json() + a hand-rolled
path.write_text(json.dumps(data)) + reseal_board(resplit=True) -- the same "manual trap" shape
already fixed for patch_vision_gemini.py/patch_owner_mailing.py/patch_court_detail.py (see
docs/HANDOFF.md items 21-25), which this script was explicitly flagged (item 24) as NOT sharing
in, because distress_score.score_board() groups every listing by parcel key first and scores each
group from the union of signals across every listing in it -- a whole-board, cross-row operation
none of the existing per-row-bounded primitives (board_stream.iter_board_rows() +
patch_existing_rows()) could support UNCHANGED.

board_dedupe_stream.stream_score_board() closes that gap: it runs the REAL, UNMODIFIED
score_board() -- not a reimplementation -- over a population of LIGHTWEIGHT Listings built by
streaming the board once (only the ~15 scalar fields and ~33 raw sub-keys scoring actually reads;
see that module's own docstring for the full design and the grep that produced the whitelist),
then diffs each row's new distress_stack against the one already published and returns ONLY the
rows that actually changed, ready for web_artifact.patch_existing_rows(). This script never holds
the whole board as full Listing objects, and the write at the end is a targeted patch, not a
whole-file rewrite -- patch_existing_rows() itself regenerates docs/listings.json + the gzipped
parts + the manifest in one streaming pass, so the separate reseal_board(resplit=True) call this
script used to need is gone too (patch_existing_rows() already does that job).

Still does NOT publish the slim payload or detail shards (same disclosed gap
patch_existing_rows() itself has, which this script already lived with before this migration) --
see the closing message below.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.board_dedupe_stream import stream_score_board
from foreclosure_scraper.distress_score import ScoreBoardError
from foreclosure_scraper.web_artifact import BoardLockBusy, board_lock, patch_existing_rows

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    # THE LOCK. This script patches docs/listings.json in place, so it is a board writer like
    # any other and must not run beside one -- the loser's work is silently reverted, with no
    # error anywhere. See web_artifact.board_lock.
    try:
        with board_lock(REPO, owner="patch_distress_score.py"):
            return _run()
    except BoardLockBusy as exc:
        print(f"{exc} -- skipping.", flush=True)
        return 0


def _run() -> int:
    docs = REPO / "docs"
    try:
        result = stream_score_board(docs)
    except ScoreBoardError as exc:
        # Never leave a partially-scored board on disk: score_board()'s own convention (mirrored
        # by daily_api_refresh.py/main.py) is that a scoring failure aborts the write entirely.
        print(f"[{time.strftime('%H:%M:%S')}] SCORE_BOARD_FAILED: {exc} -- not patching.",
              flush=True)
        return 6

    print(f"[{time.strftime('%H:%M:%S')}] scanned {result['scanned']:,} rows "
          f"({result['skipped']} unparseable skipped) | tiers: {result['tiers']}", flush=True)
    if result["dropped_key_collisions"]:
        print(f"  dropped {result['dropped_key_collisions']} dedupe_key collision(s) "
              f"(ambiguous across >1 board row -- never guessed)", flush=True)

    patches = result["patches"]
    if not patches:
        print(f"[{time.strftime('%H:%M:%S')}] every row's distress_stack already matches -- "
              f"nothing to patch.", flush=True)
        return 0

    stats = patch_existing_rows(
        patches,
        {"notes": f"stream_score_board: {result['changed']} distress_stack change(s) "
                  f"({result['stack_removed']} removed)"},
        docs_dir=docs,
    )
    print(f"[{time.strftime('%H:%M:%S')}] patched {stats['applied']:,} row(s) "
          f"({stats['matched']:,} matched, {stats['not_found']} not found, "
          f"{stats['duplicate_key_matches']} keys shared by >1 row) -- "
          f"board now {stats['total_after']:,} rows.", flush=True)

    # THIS SCRIPT DOES NOT FULLY PUBLISH. patch_existing_rows() regenerates docs/listings.json,
    # the gzipped parts, listings_detail.json(.gz) and the manifest -- but, like
    # append_new_rows()/merge_duplicate_rows(), deliberately does NOT regenerate
    # docs/listings_slim.json.gz or docs/detail_shards/ (the index-aligned mobile payloads only
    # the full write_artifact() pipeline emits). Pushing a board without them ships a fresh board
    # beside a slim file and a shard set describing the PREVIOUS one, so this script leaves them
    # exactly as they were and lets the next write_artifact() caller (the daily vision pass, the
    # noon lrcpwa pass, run_local.sh) re-emit all four payloads together, joined correctly.
    print(f"[{time.strftime('%H:%M:%S')}] NOT PUBLISHING listings_slim.json.gz/detail_shards/ -- "
          "this script cannot regenerate them; they ship correctly on the next write_artifact() "
          "publish.\n  To publish now:  uv run python scripts/recompute_valuation.py",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
