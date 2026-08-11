#!/bin/zsh
# Noon land-records refresh: fill lrcpwa addresses/values/photos deferred by the
# API rate limit, recompute tags, commit + push. Guards against a running weekly.
set -uo pipefail
ROOT="$HOME/foreclosure-scraper"; cd "$ROOT" || exit 1
LOG="/tmp/lrcpwa_refresh.log"
exec >> "$LOG" 2>&1
echo "=== lrcpwa_refresh $(date) ==="
# one board-writer at a time — skip if a full run / merge is active.
# Unescaped alternation: pgrep -f uses ERE, where `\|` is a LITERAL pipe (it
# matched nothing, so this guard silently never fired — double board-writer +
# git race every Tue/Fri). Matches the working sos_agent_refresh.sh pattern.
#
# patch_vision_gemini.py IS A BOARD WRITER AND WAS NOT LISTED. The 09:30 vision
# job runs up to VISION_MAX_SECONDS=14400 (4h), so it is still holding a board
# it loaded at 09:33 when this 12:00 job fires. On 2026-08-10 this pass resolved
# 1,064 parcels, filled 343 county values, tagged 410 absentee owners, wrote
# 38,500 listings and pushed — and the vision job wrote its 09:33 board back at
# 13:36 and reverted every one of them. The board still carries the 09:33
# strategy_fit count, three publishes later. Nothing errored.
#
# This guard is still TOCTOU-racy by construction (a real lock belongs around
# load_board -> mutate -> write_artifact in every wrapper). It closes the
# recurring daily case; it is not the general fix.
if pgrep -f "merge_today_sources.py" >/dev/null \
   || pgrep -f "foreclosure_scraper.__main__|-m foreclosure_scraper|run_local.sh" >/dev/null \
   || pgrep -f "patch_vision_gemini.py|daily_api_refresh.py|patch_court_detail.py" >/dev/null \
   || pgrep -f "recompute_valuation.py|regenerate_dashboard.py|sos_agent_refresh.py" >/dev/null; then
  echo "board-writer active — skipping this noon run"; exit 0
fi
/Users/cashhigh/.local/bin/uv run python scripts/lrcpwa_refresh.py || { echo "pass failed rc=$?"; exit 1; }
# commit + push the refreshed board (+ any new photos)
# .gz twins only — the uncompressed listings.json/.detail.json are gitignored
# (over GitHub's 100MB limit; load_board rebuilds from the .gz). Naming an
# ignored path in git add fails the whole command.
# docs/listings_slim.json.gz is the payload PHONES fetch. This script calls
# write_artifact(), so it regenerates the slim file — but it used to commit the
# fat board and run_meta while leaving the fresh slim uncommitted, which puts
# phones on a stale board (or a blank one, when the record count moves) until
# the next publisher that stages it. Desktop looked perfect the whole time.
#
# Gate on "exists OR is already tracked", not just "exists": a pathspec matching
# no file AND not in the index makes `git add` exit 128 and stage NOTHING AT ALL,
# but once the file is tracked we must still be able to stage its DELETION —
# that is how the emitter's delete-on-failure path reaches the live site.
PUB=(docs/listings.json.gz docs/listings_detail.json.gz
     docs/run_meta.json docs/parcel_photos)
if [ -f docs/listings_slim.json.gz ] \
   || git ls-files --error-unmatch docs/listings_slim.json.gz >/dev/null 2>&1; then
  PUB+=(docs/listings_slim.json.gz)
fi
# docs/detail_shards/ is the per-lead detail payload phones fetch, emitted by the
# same write_artifact() call this script makes. Same gate, same reason — and a
# DIRECTORY pathspec behaves the same way as a file here: absent AND untracked
# exits 128 and stages nothing at all, while `git add docs/detail_shards` on a
# tracked directory stages additions, modifications AND deletions inside it,
# which is what carries the emitter's remove-the-directory failure path through
# to the live site.
if [ -d docs/detail_shards ] \
   || git ls-files --error-unmatch docs/detail_shards >/dev/null 2>&1; then
  PUB+=(docs/detail_shards)
fi
git add "${PUB[@]}" 2>/dev/null
if ! git diff --cached --quiet; then
  git commit -q -m "Scheduled land-records refresh: lrcpwa addresses/values/photos + tags

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>" && git push 2>&1 | tail -1
  echo "committed + pushed"
else
  echo "no board changes to commit"
fi
echo "=== done $(date) ==="
