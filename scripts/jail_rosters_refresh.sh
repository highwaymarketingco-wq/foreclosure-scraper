#!/bin/zsh
# Daily launchd wrapper for backfill_jail_rosters.py --apply (added 2026-11-23, first
# real --apply landed as bdddd45 after the board_lock wait= fix in b2a1a32). The script
# acquires its own board_lock internally (wait=1800, poll=10) -- this wrapper does NOT
# also take board_lock_acquire, that would be redundant with/conflict against it.
#
# Once-daily, not a 5-min supervisor: the script does one full 33-county pass per
# invocation and exits; there is nothing to "relaunch if dead" the way incarceration/
# bop_federal (continuous paced loops) need.
set -u
ROOT=/Users/cashhigh/foreclosure-scraper
cd "$ROOT" || exit 1
LOG="$ROOT/logs/jail_rosters_refresh.log"
mkdir -p "$ROOT/logs"

. "$ROOT/scripts/job_event.sh"
job_event_begin jail_rosters
trap 'job_event_finalize' EXIT INT TERM

echo "=== jail_rosters_refresh $(date) ===" >> "$LOG"
job_run "${JAIL_ROSTERS_TIMEOUT:-3600}" "$ROOT/.venv/bin/python3" scripts/backfill_jail_rosters.py --apply >>"$LOG" 2>&1
RC=$JOB_RUN_RC
if [ "$RC" -ne 0 ]; then
  echo "=== jail_rosters FAILED rc=$RC ===" >> "$LOG"
  job_event_end failed "" "rc=$RC"
  exit 1
fi
job_event_end ok ""
