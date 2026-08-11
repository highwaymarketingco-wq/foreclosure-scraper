#!/bin/zsh
# Noon land-records refresh: fill lrcpwa addresses/values/photos deferred by the
# API rate limit, recompute tags, commit + push. Guards against a running weekly.
set -uo pipefail
ROOT="$HOME/foreclosure-scraper"; cd "$ROOT" || exit 1
LOG="/tmp/lrcpwa_refresh.log"
exec >> "$LOG" 2>&1
echo "=== lrcpwa_refresh $(date) ==="

# ONE BOARD WRITER AT A TIME — a real lock, held across the whole
# load_board -> mutate -> write_artifact -> commit span.
#
# What used to be here was a pgrep list, and it was TOCTOU-racy by construction:
# a check taken BEFORE the critical section can always lose to a writer that
# starts after it. It also had to be kept in sync by hand, which it never was —
# patch_vision_gemini.py was missing from it, and the 09:30 vision job runs up
# to VISION_MAX_SECONDS=14400 (4h), so it is still holding a board it loaded at
# 09:33 when this 12:00 job fires. On 2026-08-10 this pass resolved 1,064
# parcels, filled 343 county values, tagged 410 absentee owners, wrote 38,500
# listings and pushed — and the vision job wrote its 09:33 board back at 13:36
# and reverted every one of them. The board still carried the 09:33
# strategy_fit count three publishes later. Nothing errored.
#
# The lock is FORECLOSURE_BOARD_LOCK_HELD-reentrant, so scripts/lrcpwa_refresh.py
# (which asks for it too) proceeds inside this one instead of deadlocking, and
# a lock left by a killed process is broken automatically — see
# scripts/board_lock.sh.
. "$ROOT/scripts/board_lock.sh"
. "$ROOT/scripts/board_payload.sh"
if ! board_lock_acquire "$ROOT" "lrcpwa_refresh.sh"; then
  echo "board-writer active ($(board_lock_holder)) — skipping this noon run"; exit 0
fi
trap 'board_lock_release' EXIT INT TERM

/Users/cashhigh/.local/bin/uv run python scripts/lrcpwa_refresh.py || { echo "pass failed rc=$?"; exit 1; }
# commit + push the refreshed board (+ any new photos). The payload list, and
# every "exists OR is already tracked" rule behind it, now lives in ONE place —
# scripts/board_payload.sh — because five publishers were each maintaining their
# own copy of it and they had already drifted apart.
board_payload_check "$ROOT" || true   # loud, non-fatal: see board_payload.sh
board_payload_add "$ROOT"
if ! git diff --cached --quiet; then
  git commit -q -m "Scheduled land-records refresh: lrcpwa addresses/values/photos + tags

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
  # REBASE BEFORE PUSH. A bare `git push` that loses a race leaves the commit
  # local and main diverged — and then EVERY later run stages a diff that is
  # already committed, sees an empty staged diff, prints "no board changes to
  # commit" and stops publishing. Silently, until a human notices the live site
  # has stopped moving. The three Python publishers already do this; these two
  # shell ones did not.
  git pull --rebase --autostash origin main >/dev/null 2>&1 || true
  # NOT `git push … | tail -1`: a pipeline's status is the LAST command's, so
  # tail's 0 would mask every push failure this branch exists to report.
  if PUSH_OUT=$(git push origin main 2>&1); then
    echo "committed + pushed"
  else
    echo "!! commit made locally but PUSH FAILED — main has diverged, publishing is stopped"
    printf '%s\n' "$PUSH_OUT" | tail -3
  fi
else
  echo "no board changes to commit"
fi
echo "=== done $(date) ==="
