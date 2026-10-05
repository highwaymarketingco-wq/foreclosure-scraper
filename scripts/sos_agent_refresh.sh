#!/bin/zsh
# Daily NC SOS registered-agent lookups: the MAC side of the Mac -> VM hand-off (2026-10-05).
# Runs at 14:00 ET from the INSTALLED ~/Library/LaunchAgents/com.highway.foreclosure.sosagent.plist
# (the not-installed template deploy/mac/com.highway.foreclosure.sosagent.plist proposes 08:30).
#
# This job NO LONGER WRITES THE BOARD. It looks up up to SOS_AGENT_MAX_CHECK (150) new NC
# entities a day (adaptive: half the cap after a breaker trip or a mostly-failed run, floor 40;
# +25 back toward the max after each clean run), merges every answer into the cumulative
# hand-off file docs/handoff/sos_agent_results.json, and commits + pushes ONLY that file. The
# Oracle VM's nightly run attaches the profiles to the board (sos_agent_handoff.py).
#
# So there is no board lock around the run any more (it took the whole board for 40 minutes
# to write nothing). scripts/sos_agent_refresh.py takes the board lock itself, briefly, only
# around the git commit and the rebase, and holds its own run lock
# (logs/.sos_agent_refresh.lock) so two SOS runs -- two stealth browsers -- never overlap.
set -uo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
ROOT="${FORECLOSURE_ROOT:-$HOME/foreclosure-scraper}"; cd "$ROOT" || exit 1
mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/sos_agent_refresh.log"       # was /tmp, which a reboot empties (audit O10)
exec >> "$LOG" 2>&1
echo "=== sos_agent_refresh $(date) ==="

. "$ROOT/scripts/job_event.sh"
JOB_EVENT_ROOT="$ROOT"
job_event_begin sosagent
trap 'job_event_finalize' EXIT INT TERM

if ! command -v uv >/dev/null 2>&1; then
  echo "!! uv not found on PATH ($PATH)"; job_event_end failed "" "uv_not_found"; exit 127
fi

export SOS_AGENT=1
export SOS_AGENT_MAX_CHECK="${SOS_AGENT_MAX_CHECK:-150}"       # adaptive cap ceiling
export SOS_AGENT_MIN_CHECK="${SOS_AGENT_MIN_CHECK:-40}"        # back-off floor
export SOS_AGENT_CAP_STEP="${SOS_AGENT_CAP_STEP:-25}"          # step up after a clean run
export SOS_AGENT_BREAKER_FAILS="${SOS_AGENT_BREAKER_FAILS:-6}"
export SOS_AGENT_MAX_SECONDS="${SOS_AGENT_MAX_SECONDS:-2700}"  # lookup budget: 150 x ~10 s fits
export SOS_AGENT_OUTCOME_FILE="$ROOT/logs/.sos_agent_outcome"
rm -f "$SOS_AGENT_OUTCOME_FILE"
# SOS_AGENT_CAP=N: a one-off small run by hand (passes --cap N; never raises the adaptive cap).
SOS_ARGS=()
[ -n "${SOS_AGENT_CAP:-}" ] && SOS_ARGS=(--cap "$SOS_AGENT_CAP")

# Hard kill for the whole pass: the 45-min lookup budget + the board scan + the git push.
# SOS_MAX_RUNTIME is the old name (it was the board lock's max runtime) and still works.
job_run "${SOS_TIMEOUT:-${SOS_MAX_RUNTIME:-4200}}" uv run python scripts/sos_agent_refresh.py "${SOS_ARGS[@]}"
RC=$JOB_RUN_RC
if [ "$RC" -ne 0 ]; then
  echo "pass failed rc=$RC"; job_event_end failed "" "rc=$RC"; exit 1
fi

OUTCOME="failed"; ROWS=""; NOTE="the pass exited 0 without reporting an outcome"
if [ -f "$SOS_AGENT_OUTCOME_FILE" ]; then
  OUTCOME="$(sed -n 1p "$SOS_AGENT_OUTCOME_FILE")"
  ROWS="$(sed -n 2p "$SOS_AGENT_OUTCOME_FILE")"
  NOTE="$(sed -n 3p "$SOS_AGENT_OUTCOME_FILE")"
fi
echo "outcome: $OUTCOME ${ROWS:+($ROWS resolved)} $NOTE"
job_event_end "$OUTCOME" "$ROWS" "$NOTE"
echo "=== done $(date) ==="
