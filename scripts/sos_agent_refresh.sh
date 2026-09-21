#!/bin/zsh
# Daily NC SOS registered-agent pass: advance the entity-contact frontier by ~40 new
# NC LLC leads/day (gentle on sosnc.gov — the enricher skips already-resolved names
# and back-off is enforced by a fast circuit breaker). Scheduled at 08:30 by
# deploy/mac/com.highway.foreclosure.sosagent.plist, right after lrcpwa. Commits ONLY
# when new contacts actually landed (a Cloudflare-walled run bails fast with 0 changes
# and must not create an empty commit).
set -uo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
ROOT="${FORECLOSURE_ROOT:-$HOME/foreclosure-scraper}"; cd "$ROOT" || exit 1
mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/sos_agent_refresh.log"       # was /tmp, which a reboot empties (audit O10)
exec >> "$LOG" 2>&1
echo "=== sos_agent_refresh $(date) ==="

. "$ROOT/scripts/job_event.sh"
. "$ROOT/scripts/board_lock.sh"
. "$ROOT/scripts/board_payload.sh"
. "$ROOT/scripts/publish_helper.sh"
JOB_EVENT_ROOT="$ROOT"
job_event_begin sosagent
trap 'job_event_finalize; board_lock_release' EXIT INT TERM

if ! command -v uv >/dev/null 2>&1; then
  echo "!! uv not found on PATH ($PATH)"; job_event_end failed "" "uv_not_found"; exit 127
fi

# ONE BOARD WRITER AT A TIME — a real lock held across the whole
# load_board -> mutate -> write_artifact -> commit span, replacing the
# hand-maintained pgrep list that used to be here. See lrcpwa_refresh.sh and
# scripts/board_lock.sh.
if ! board_lock_acquire "$ROOT" "sos_agent_refresh.sh" 0 "${SOS_MAX_RUNTIME:-3600}"; then
  echo "$(board_lock_refusal_message 'this run')"
  if [ "$BOARD_LOCK_REFUSAL" = "memory" ]; then
    job_event_end skipped_memory "" "$BOARD_MEM_REASON"
  else
    job_event_end skipped_lock "" "$(board_lock_holder)"
  fi
  exit 0
fi

export SOS_AGENT=1
export SOS_AGENT_MAX_CHECK="${SOS_AGENT_MAX_CHECK:-40}"
export SOS_AGENT_BREAKER_FAILS="${SOS_AGENT_BREAKER_FAILS:-6}"
job_run "${SOS_TIMEOUT:-2400}" uv run python scripts/sos_agent_refresh.py
RC=$JOB_RUN_RC
if [ "$RC" -ne 0 ]; then
  echo "pass failed rc=$RC"; job_event_end failed "" "rc=$RC"; exit 1
fi

# commit ONLY if the board data changed (not run_meta's timestamp) — a walled run
# rewrites listings.json byte-identically and must not commit. THE CHANGE GATE
# COVERS EVERYTHING THE `git reset -q` CAN THROW AWAY (publish_commit's "payload"
# mode): it used to watch board/detail/shards only, so a run whose only effect was
# on docs/listings_slim.json.gz (the payload phones fetch) was told "no change",
# reset it, and never published it.
publish_commit "$ROOT" "Scheduled SOS pass: +NC entity registered-agent contacts

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>" payload
PC=$?
board_lock_release      # the lock protects the write and the commit, not the network

case $PC in
  0)
    if publish_push "$ROOT"; then
      echo "committed + pushed"; job_event_end ok
    else
      echo "!! commit made locally but PUSH FAILED — the next publisher's push will carry it"
      printf '%s\n' "$PUBLISH_PUSH_OUT"
      job_event_end push_failed "" "$PUBLISH_PUSH_OUT"
    fi ;;
  1) echo "no new contacts (sosnc.gov may be rate-limited) — no commit"
     job_event_end no_change ;;
  *) echo "!! commit refused (size gate or hook) — see logs/publish_blocked.log"
     job_event_end failed "" "commit_failed"; exit 1 ;;
esac
echo "=== done $(date) ==="
