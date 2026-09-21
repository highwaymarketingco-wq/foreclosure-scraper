#!/bin/zsh
# Shared driver for the per-family scheduled merge jobs (audit O2). Source this from
# scripts/run_family_<family>.sh and call `family_job <family>`; see scripts/family_merge.py.
#
#   phase 1  scrape  NO LOCK.  The network-bound part; stages leads in data/family_stage/.
#   phase 2  merge   LOCK.     load board -> merge staged leads -> enrich -> write.
#   phase 3  post    LOCK.     optional follow-up (qpaybill: balances), FAMILY_POST=1.
#   then     commit inside the lock, release it, push with timeout + retries.
#
# Each phase has its own wall-clock cap (macOS has no timeout(1); scripts/run_timeout.pl),
# the whole job writes ONE line to logs/job_events.jsonl, and a busy lock is a skip with
# the staged data kept for the next run, never a failure.
#
# Knobs (env, all optional):
#   FAMILY_SCRAPE_TIMEOUT  seconds for phase 1        (per-wrapper default)
#   FAMILY_MERGE_TIMEOUT   seconds for phase 2        (per-wrapper default)
#   FAMILY_POST_TIMEOUT    seconds for phase 3        (default 3600)
#   FAMILY_LOCK_WAIT       seconds to wait for a busy lock (default 1800)
#   FAMILY_SKIP_SCRAPE=1   merge what is already staged (used after a busy-lock skip)

family_job() {
  FAM="$1"
  _fjmode="${FAMILY_COMMIT_MODE:-payload}"
  set -uo pipefail
  export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
  ROOT="${FORECLOSURE_ROOT:-$HOME/foreclosure-scraper}"; cd "$ROOT" || return 1
  mkdir -p "$ROOT/logs"
  LOG="$ROOT/logs/family_${FAM}.log"
  exec >> "$LOG" 2>&1
  echo "=== family_${FAM} $(date) ==="

  . "$ROOT/scripts/job_event.sh"
  . "$ROOT/scripts/board_lock.sh"
  . "$ROOT/scripts/board_payload.sh"
  . "$ROOT/scripts/publish_helper.sh"
  JOB_EVENT_ROOT="$ROOT"
  job_event_begin "family_${FAM}"
  trap 'job_event_finalize; board_lock_release; rm -f "${FAMILY_ROWS_FILE:-/nonexistent}"' EXIT INT TERM

  if ! command -v uv >/dev/null 2>&1; then
    echo "!! uv not found on PATH ($PATH)"; job_event_end failed "" "uv_not_found"; return 127
  fi
  # The scrape phase holds no lock but is still a memory hog (audit O9): run the gate.
  _blroot="$ROOT"
  board_mem_gate "family_${FAM}" || {
    echo "memory gate refused ($BOARD_MEM_REASON) - skipping this run"
    job_event_end skipped_memory "" "$BOARD_MEM_REASON"; return 0
  }
  export FAMILY_ROWS_FILE="$ROOT/logs/.family_${FAM}.rows.$$"
  _fjscrape="${FAMILY_SCRAPE_TIMEOUT:-14400}"
  _fjmerge="${FAMILY_MERGE_TIMEOUT:-5400}"
  _fjpost="${FAMILY_POST_TIMEOUT:-3600}"

  # ---- phase 1: scrape, NO lock -------------------------------------------------------
  if [ "${FAMILY_SKIP_SCRAPE:-0}" != "1" ]; then
    echo "--- phase 1: scrape ($(date +%T), cap ${_fjscrape}s)"
    job_run "$_fjscrape" uv run python scripts/family_merge.py "$FAM" --phase scrape
    _fjrc=$JOB_RUN_RC
    if [ "$_fjrc" -eq 124 ]; then
      echo "!! scrape hit its ${_fjscrape}s cap; merging whatever finished and was staged"
    elif [ "$_fjrc" -ne 0 ]; then
      echo "!! scrape rc=$_fjrc (nothing staged or the runner failed)"
      job_event_end failed "" "scrape_rc=$_fjrc"; return 1
    fi
  fi

  # ---- phase 2: merge, under the lock -------------------------------------------------
  if ! board_lock_acquire "$ROOT" "family_${FAM}" "${FAMILY_LOCK_WAIT:-1800}" $(( _fjmerge + 1800 )); then
    echo "$(board_lock_refusal_message "the ${FAM} merge") - staged data kept for the next run"
    if [ "$BOARD_LOCK_REFUSAL" = "memory" ]; then job_event_end skipped_memory "" "$BOARD_MEM_REASON"
    else job_event_end skipped_lock "" "$(board_lock_holder)"; fi
    return 0
  fi
  echo "--- phase 2: merge ($(date +%T), cap ${_fjmerge}s)"
  job_run "$_fjmerge" uv run python scripts/family_merge.py "$FAM" --phase merge
  _fjrc=$JOB_RUN_RC
  if [ "$_fjrc" -ne 0 ]; then
    echo "!! merge rc=$_fjrc - board NOT published"
    job_event_end failed "" "merge_rc=$_fjrc"; return 1
  fi

  # ---- phase 3: optional post step ----------------------------------------------------
  if [ "${FAMILY_POST:-0}" = "1" ]; then
    echo "--- phase 3: post ($(date +%T), cap ${_fjpost}s)"
    job_run "$_fjpost" uv run python scripts/family_merge.py "$FAM" --phase post
    _fjrc=$JOB_RUN_RC
    [ "$_fjrc" -ne 0 ] && echo "!! post step rc=$_fjrc (the merge itself landed; continuing to publish)"
  fi

  # ---- commit INSIDE the lock, release, then push -------------------------------------
  _fjrows=$(cat "$FAMILY_ROWS_FILE" 2>/dev/null)
  publish_commit "$ROOT" "Scheduled family merge (${FAM}): ${_fjrows:-?} rows staged

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>" "$_fjmode"
  _fjpc=$?
  board_lock_release
  case $_fjpc in
    0)
      if publish_push "$ROOT"; then
        echo "committed + pushed"; job_event_end ok "${_fjrows:-}"
      else
        echo "!! commit made locally but PUSH FAILED - the next publisher's push will carry it"
        printf '%s\n' "$PUBLISH_PUSH_OUT"
        job_event_end push_failed "${_fjrows:-}" "$PUBLISH_PUSH_OUT"
      fi ;;
    1) echo "no board changes to commit"; job_event_end no_change "${_fjrows:-}" ;;
    *) echo "!! commit refused (size gate or hook) - see logs/publish_blocked.log"
       job_event_end failed "" "commit_failed"; return 1 ;;
  esac
  echo "=== done $(date) ==="
  return 0
}
