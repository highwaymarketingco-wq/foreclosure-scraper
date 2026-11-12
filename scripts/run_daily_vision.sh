#!/usr/bin/env bash
# Daily incremental Gemini Vision pass.
#
# The weekly crawl (run_local.sh) refreshes the data; this fills in AI
# condition-analysis on the un-scored listings each day, up to whatever free
# Gemini quota allows that day. Over the week, coverage builds up. Then it
# republishes the dashboard. Free — uses the rotating Gemini keys in .secrets/.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SECRETS="$ROOT/.secrets"
mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/daily-vision-$(date +%Y%m%dT%H%M%S).log"

# launchd hands a job a minimal PATH; dailycourt failed 31 days running on "uv: command not found"
# and nobody was told (audit O10/O12). Set it, and fail loudly if uv is still missing.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"

. "$ROOT/scripts/job_event.sh"
. "$ROOT/scripts/board_lock.sh"
. "$ROOT/scripts/board_payload.sh"
. "$ROOT/scripts/publish_helper.sh"
JOB_EVENT_ROOT="$ROOT"
job_event_begin dailyvision
# One trap for the whole job: an exit that never reported an outcome is recorded as failed
# (a killed run, on 8/27, 9/7, 9/10 and 9/17, left no trace at all), and the lock is released.
trap 'job_event_finalize; board_lock_release' EXIT INT TERM

if ! command -v uv >/dev/null 2>&1; then
  echo "==> uv not found on PATH ($PATH) - cannot run daily-vision." | tee -a "$LOG"
  job_event_end failed "" "uv_not_found"; exit 127
fi

# THE Tue/Fri SKIP THAT WAS HERE IS GONE (audit O2). It read FULL_RUN_DAYS="2 5" and exited 0
# "because the weekly run_local.sh handles today", but the weekly job is a popup that does
# nothing unless a human answers it within two hours (and it wrote no log), so Tue and Fri
# refreshed NOTHING: 6 dead days since 8/29. The board lock already stops this job overlapping a
# real full run (run_local.sh holds it 15 to 57 hours), so the skip bought no safety and cost
# two refreshes a week.

# ONE BOARD WRITER AT A TIME — a real lock, held for this whole script.
#
# This replaces two weaker guards that used to sit here: a pgrep list (TOCTOU by
# construction — a check before the critical section can always lose to a writer
# that starts after it) and a private .daily-vision.lock that only ever excluded
# ANOTHER COPY OF THIS SCRIPT. The second one is the important loss: this job
# holds a loaded board for up to VISION_MAX_SECONDS=14400 (4h), and the private
# lock did nothing to stop the noon lrcpwa pass and the 2pm SOS pass writing
# inside that window. On 2026-08-10 this job wrote its 09:33 board back at 13:36
# and reverted the noon pass's 1,064 resolved parcels, 343 county values and 410
# absentee tags. Nothing errored.
#
# The lock covers daily_api_refresh.py AND patch_vision_gemini.py, both of which
# are board writers, and it is reentrant via FORECLOSURE_BOARD_LOCK_HELD so each
# of them proceeds inside this lock rather than deadlocking against it. A lock
# left behind by a killed run is broken automatically — see scripts/board_lock.sh.
# max runtime 4 h: the API phase is 12 to 33 minutes normally and vision is now boxed to 90.
# A holder past that + 30 minutes is treated as hung and its lock broken (audit O11).
if ! board_lock_acquire "$ROOT" "run_daily_vision.sh" 0 "${DAILY_LOCK_MAX_RUNTIME:-14400}"; then
  echo "==> $(board_lock_refusal_message 'daily-vision')." | tee -a "$LOG"
  if [ "$BOARD_LOCK_REFUSAL" = "memory" ]; then job_event_end skipped_memory "" "$BOARD_MEM_REASON"
  else job_event_end skipped_lock "" "$(board_lock_holder)"; fi
  exit 0
fi
# The two python publishers COMMIT inside the lock but do not push (audit O7): this wrapper
# releases the lock and pushes afterwards with a timeout and retries, so a stalled 150 MB push
# can no longer hold the board while every other job skips.
export BOARD_PUSH_DEFERRED=1

# Local Ollama removed (redundant vs the 4 cloud pools; too slow/weak on 8GB).
# Re-enable by installing Ollama + `ollama pull qwen2.5vl:3b` and unsetting this.
export VISION_USE_OLLAMA=0

# Load every free vision credential present. The vision pool uses ALL of them
# (each Gemini key = one project's free quota; GitHub Models + Groq + local
# Ollama are separate free pools) and rotates across them.
load() { [[ -f "$2" ]] && export "$1"="$(cat "$2")"; }
load GEMINI_API_KEY   "$SECRETS/gemini_api_key.txt"
for i in $(seq 1 60); do load "GEMINI_API_KEY_$i" "$SECRETS/gemini_api_key_$i.txt"; done

# GitHub Models (free) — prefer a saved token, else fall back to the gh CLI.
load GITHUB_MODELS_TOKEN "$SECRETS/github_models_token.txt"
[[ -z "${GITHUB_MODELS_TOKEN:-}" ]] && export GITHUB_MODELS_TOKEN="$(gh auth token 2>/dev/null || true)"
# Groq (free) — optional, only if a key is dropped in.
load GROQ_API_KEY "$SECRETS/groq_api_key.txt"
# More free API pools — each activates only if its key file exists.
load OPENROUTER_API_KEY    "$SECRETS/openrouter_api_key.txt"
load MISTRAL_API_KEY       "$SECRETS/mistral_api_key.txt"
load CLOUDFLARE_API_TOKEN  "$SECRETS/cloudflare_api_token.txt"
load CLOUDFLARE_ACCOUNT_ID "$SECRETS/cloudflare_account_id.txt"
# NVIDIA NIM (free) — one key, many vision models (each its own ~40 RPM lane).
load NVIDIA_API_KEY        "$SECRETS/nvidia_api_key.txt"

export VISION_PROVIDER=gemini
# Let the free DAILY QUOTA (and the 4h wall clock below) be the limiter, not an
# arbitrary count. 1500 was NOT letting quota be the limiter: every recent pass
# drained its 1500 and exited with unscored_remaining=0 in 5-17 minutes out of a
# 4-hour budget (logs/daily-vision-*.log: 972 scored in 999s, 976 in 1006s, 956
# in 991s). 6000 was raised for the same reason on 2026-07: measured 2026-08-07,
# the eligible-and-unscored backlog is 9,326 (board has grown since 6000 was
# set), so 6000 was ITSELF now the arbitrary limiter it was raised to eliminate.
# 15000 comfortably clears today's backlog with room for board growth; quota/
# time remain the real stop, same as the 6000->1500 change.
export VISION_MAX_LISTINGS="${VISION_MAX_LISTINGS:-15000}"
export VISION_INTER_CALL_DELAY="${VISION_INTER_CALL_DELAY:-4}"
# Free-tier 429s are usually PER-MINUTE rate limits, not daily exhaustion. Keep a
# rate-limited backend cooling-down-and-retrying instead of retiring it after 2
# strikes (which used to kill the whole 9-key Gemini fleet in ~2 min). High strike
# tolerance + a cooldown that outlasts the 1-min window keeps the pool alive so it
# scores steadily whenever quota frees up.
export VISION_BACKEND_STRIKES="${VISION_BACKEND_STRIKES:-10}"
export VISION_BACKEND_COOLDOWN="${VISION_BACKEND_COOLDOWN:-70}"
# Wall-clock cap so a slow local-Ollama floor pass can't run into the next
# scheduled job (which the lock above would otherwise make skip). 4h.
# 90 MINUTES, not 4 hours (audit O6): vision scored 371 to 759 listings a day while holding the
# lock 3h51m to 5h55m (live_workers collapses from 21 to 1 within ~40 minutes on every run), which
# is why lrcpwa and SOS skipped on most days. patch_vision_gemini.py also stops early when
# scored/hour falls under 100 (VISION_MIN_SCORED_PER_HOUR) and enrichment_vision stops when the
# worker pool stays at 2 or fewer for 15 minutes (VISION_YIELD_LIVE_MIN / VISION_YIELD_LIVE_S).
export VISION_MAX_SECONDS="${VISION_MAX_SECONDS:-5400}"
export PYTHONUNBUFFERED=1

# Daily API refresh FIRST: re-pull the browserless JSON sources (Fannie REO,
# HUD, VA, foreclosure.com, CourtListener…) and merge, so day-old REO that has
# sold drops out and its deep-link stops 404'ing, and fresh inventory appears.
# Runs before vision so vision scores the now-current set. Non-fatal: if it
# fails we still run vision on yesterday's data.
echo "==> daily api refresh (fresh Fannie/REO links, kills 404s) $(date)" | tee -a "$LOG"
API_START_LINE=$(wc -l < "$LOG" | tr -d ' ')
job_run "${API_TIMEOUT:-5400}" uv run python scripts/daily_api_refresh.py >>"$LOG" 2>&1
API_RC=$JOB_RUN_RC
FAIL_NOTE=""
if [ "$API_RC" -ne 0 ]; then
  echo "==> !! api refresh FAILED rc=$API_RC (continuing to vision on existing data)" | tee -a "$LOG"
  FAIL_NOTE="api_rc=$API_RC"
fi
# Fail LOUDLY (audit O6) when the count guard fired, a scorer failed, or more than 4 of the 14
# refreshed sources were carried over. The API phase's log lines are the evidence.
API_LOG=$(tail -n +"$((API_START_LINE + 1))" "$LOG")
if printf '%s\n' "$API_LOG" | grep -q "COUNT GUARD"; then
  echo "==> !! COUNT GUARD refused the API refresh's board write" | tee -a "$LOG"
  FAIL_NOTE="$FAIL_NOTE count_guard"
fi
if printf '%s\n' "$API_LOG" | grep -q "SCORE_BOARD_FAILED"; then
  echo "==> !! the scorer failed during the API refresh (tiers not refreshed)" | tee -a "$LOG"
  FAIL_NOTE="$FAIL_NOTE score_board_failed"
fi
CARRIED=$(printf '%s\n' "$API_LOG" | grep "carryover (fresh<" | tail -1 | grep -o '[A-Za-z_.]*=[0-9]*' | wc -l | tr -d ' ')
if [ "${CARRIED:-0}" -gt "${MAX_CARRIED_SOURCES:-4}" ]; then
  echo "==> !! $CARRIED of 14 sources were carried over (limit ${MAX_CARRIED_SOURCES:-4}): the daily refresh is not refreshing" | tee -a "$LOG"
  FAIL_NOTE="$FAIL_NOTE carried_over=$CARRIED"
fi

echo "==> daily vision $(date)" | tee -a "$LOG"
job_run "${VISION_JOB_TIMEOUT:-9000}" uv run python scripts/patch_vision_gemini.py >>"$LOG" 2>&1
RC=$JOB_RUN_RC
echo "==> exit=$RC $(date)" | tee -a "$LOG"
[ "$RC" -ne 0 ] && FAIL_NOTE="$FAIL_NOTE vision_rc=$RC"

# The python steps committed inside the lock; release it, THEN push (audit O7).
board_lock_release
PUSH_FAILED=0
AHEAD=$(git -C "$ROOT" rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
if [ "${AHEAD:-0}" -gt 0 ]; then
  if publish_push "$ROOT" >>"$LOG" 2>&1; then
    echo "==> pushed" | tee -a "$LOG"
  else
    echo "==> !! PUSH FAILED - the commit stays local; the next publisher carries it: $PUBLISH_PUSH_OUT" | tee -a "$LOG"
    PUSH_FAILED=1
  fi
fi
if grep -q "PUBLISH_PUSH_FAILED" <(tail -n +"$((API_START_LINE + 1))" "$LOG"); then PUSH_FAILED=1; fi

if [ -n "$FAIL_NOTE" ]; then
  osascript -e "display notification \"daily vision: $FAIL_NOTE (see logs/dailyvision.out.log)\" with title \"Foreclosure engine\"" >/dev/null 2>&1
  job_event_end failed "" "$FAIL_NOTE"
  FINAL_RC=${RC}; [ "$FINAL_RC" -eq 0 ] && FINAL_RC=4
elif [ "$PUSH_FAILED" = "1" ]; then
  job_event_end push_failed
  FINAL_RC=$RC
else
  job_event_end ok
  FINAL_RC=$RC
fi

# Keep 14 most recent daily-vision logs.
ls -1t "$ROOT"/logs/daily-vision-*.log 2>/dev/null | tail -n +15 | xargs rm -f 2>/dev/null || true
exit $FINAL_RC
