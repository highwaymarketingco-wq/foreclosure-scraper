#!/bin/zsh
# Daily 2pm NC SOS registered-agent pass: advance the entity-contact frontier
# by ~40 new NC LLC leads/day (gentle on sosnc.gov — the enricher now skips
# already-resolved names and back-off is enforced by a fast circuit breaker).
# Runs AFTER the noon lrcpwa pass, guards against any active board-writer, and
# commits ONLY when new contacts actually landed (a Cloudflare-walled run bails
# fast with 0 changes and must not create an empty commit).
set -uo pipefail
ROOT="$HOME/foreclosure-scraper"; cd "$ROOT" || exit 1
LOG="/tmp/sos_agent_refresh.log"
exec >> "$LOG" 2>&1
echo "=== sos_agent_refresh $(date) ==="

# ONE BOARD WRITER AT A TIME — a real lock held across the whole
# load_board -> mutate -> write_artifact -> commit span, replacing the
# hand-maintained pgrep list that used to be here. That list was TOCTOU-racy by
# construction and was missing patch_vision_gemini.py, which is how a 09:30
# vision job silently reverted the 12:00 lrcpwa pass on 2026-08-10. See the
# note in lrcpwa_refresh.sh and scripts/board_lock.sh.
. "$ROOT/scripts/board_lock.sh"
. "$ROOT/scripts/board_payload.sh"
if ! board_lock_acquire "$ROOT" "sos_agent_refresh.sh"; then
  echo "board-writer active ($(board_lock_holder)) — skipping this run"; exit 0
fi
trap 'board_lock_release' EXIT INT TERM

export SOS_AGENT=1
export SOS_AGENT_MAX_CHECK="${SOS_AGENT_MAX_CHECK:-40}"
export SOS_AGENT_BREAKER_FAILS="${SOS_AGENT_BREAKER_FAILS:-6}"
/Users/cashhigh/.local/bin/uv run python scripts/sos_agent_refresh.py || { echo "pass failed rc=$?"; exit 1; }

# commit ONLY if the board data changed (not run_meta's timestamp) — a walled
# run rewrites listings.json byte-identical and must not commit. The .gz is what
# the gate reads (deterministic gzip: identical data -> identical bytes).
#
# The payload list and its "exists OR is already tracked" rules live in
# scripts/board_payload.sh now — five publishers were each maintaining a copy.
board_payload_check "$ROOT" || true   # loud, non-fatal: see board_payload.sh
board_payload_add "$ROOT"

# THE CHANGE GATE MUST COVER EVERYTHING THE `git reset -q` BELOW CAN THROW AWAY.
# It listed board/detail/shards only, while the reset discards ALL of it — so a
# run whose only effect was on docs/listings_slim.json.gz (the payload phones
# fetch) staged the fresh slim, was told "no change", reset it, and never
# published it. board_payload_changed watches every staged path except
# run_meta.json (whose run_time moves every write, which would make the gate
# fire always and defeat its purpose).
if board_payload_changed "$ROOT"; then
  git commit -q -m "Scheduled SOS pass: +NC entity registered-agent contacts

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
  # REBASE BEFORE PUSH — see the note in lrcpwa_refresh.sh. A bare push that
  # loses a race leaves main diverged, and then every later run sees an empty
  # staged diff and silently stops publishing.
  git pull --rebase --autostash origin main >/dev/null 2>&1 || true
  # NOT `git push … | tail -1`: a pipeline's status is the last command's.
  if PUSH_OUT=$(git push origin main 2>&1); then
    echo "committed + pushed"
  else
    echo "!! commit made locally but PUSH FAILED — main has diverged, publishing is stopped"
    printf '%s\n' "$PUSH_OUT" | tail -3
  fi
else
  echo "no new contacts (sosnc.gov may be rate-limited) — no commit"
  git reset -q
fi
echo "=== done $(date) ==="
