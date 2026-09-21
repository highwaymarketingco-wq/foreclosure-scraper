#!/bin/zsh
# Land-records refresh: fill lrcpwa addresses/values/photos deferred by the API rate
# limit, recompute tags, commit + push. Scheduled at 08:00 by
# deploy/mac/com.highway.foreclosure.lrcpwa.plist (it was 12:00 and lost every day the
# 09:30 vision job ran long; see docs/ops_fixes_2026-09-21.md O6).
set -uo pipefail
# launchd hands a job a minimal PATH. dailycourt failed 31 days in a row with
# "uv: command not found" (audit O10/O12), so every wrapper sets it and checks.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
ROOT="${FORECLOSURE_ROOT:-$HOME/foreclosure-scraper}"; cd "$ROOT" || exit 1
mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/lrcpwa_refresh.log"          # was /tmp, which a reboot empties (audit O10)
exec >> "$LOG" 2>&1
echo "=== lrcpwa_refresh $(date) ==="

. "$ROOT/scripts/job_event.sh"
. "$ROOT/scripts/board_lock.sh"
. "$ROOT/scripts/board_payload.sh"
. "$ROOT/scripts/publish_helper.sh"
JOB_EVENT_ROOT="$ROOT"
job_event_begin lrcpwa
# ONE trap for the whole job: an unreported exit is recorded as failed, then the lock goes.
trap 'job_event_finalize; board_lock_release' EXIT INT TERM

if ! command -v uv >/dev/null 2>&1; then
  echo "!! uv not found on PATH ($PATH)"; job_event_end failed "" "uv_not_found"; exit 127
fi

# ONE BOARD WRITER AT A TIME — a real lock, held across the whole
# load_board -> mutate -> write_artifact -> COMMIT span (the push happens after it
# is released; see scripts/publish_helper.sh).
#
# What used to be here was a pgrep list, and it was TOCTOU-racy by construction:
# a check taken BEFORE the critical section can always lose to a writer that
# starts after it. On 2026-08-10 this pass resolved 1,064 parcels, filled 343
# county values, tagged 410 absentee owners, wrote 38,500 listings and pushed —
# and the 09:30 vision job wrote its 09:33 board back at 13:36 and reverted every
# one of them. Nothing errored. See scripts/board_lock.sh.
if ! board_lock_acquire "$ROOT" "lrcpwa_refresh.sh" 0 "${LRCPWA_MAX_RUNTIME:-3600}"; then
  echo "$(board_lock_refusal_message 'this run')"
  if [ "$BOARD_LOCK_REFUSAL" = "memory" ]; then
    job_event_end skipped_memory "" "$BOARD_MEM_REASON"
  else
    job_event_end skipped_lock "" "$(board_lock_holder)"
  fi
  exit 0
fi

job_run "${LRCPWA_TIMEOUT:-3300}" uv run python scripts/lrcpwa_refresh.py
RC=$JOB_RUN_RC
if [ "$RC" -ne 0 ]; then
  echo "pass failed rc=$RC"; job_event_end failed "" "rc=$RC"; exit 1
fi

# commit INSIDE the lock, then release it, then push. The payload list and every
# "exists OR is already tracked" rule live in scripts/board_payload.sh.
publish_commit "$ROOT" "Scheduled land-records refresh: lrcpwa addresses/values/photos + tags

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>" any
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
  1) echo "no board changes to commit"; job_event_end no_change ;;
  *) echo "!! commit refused (size gate or hook) — see logs/publish_blocked.log"
     job_event_end failed "" "commit_failed"; exit 1 ;;
esac
echo "=== done $(date) ==="
