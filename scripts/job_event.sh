#!/bin/sh
# One JSON line per scheduled-job outcome, appended to logs/job_events.jsonl.
# Source this; do not execute it. POSIX sh, so it works from the /bin/zsh and
# /bin/bash wrappers alike.
#
#   ROOT=/Users/me/foreclosure-scraper
#   . "$ROOT/scripts/job_event.sh"
#   job_event_begin lrcpwa                 # stamps start time + swap-out counter
#   trap 'job_event_finalize; board_lock_release' EXIT INT TERM
#   ...
#   job_run 3600 uv run python scripts/x.py    # timeout + peak RSS; sets JOB_RUN_RC
#   job_event_end ok 120                   # outcome + rows_changed
#
# WHY (audit 2026-09-21 O4, O9, O10): every scheduled job printed its outcome to a
# log under /tmp and exited 0. A skipped lock, a refused count guard, a failed push
# and a clean run looked the same to everything except a person reading the log.
# dailycourt failed 31 days running ("uv: command not found") and nobody knew.
# scripts/job_watch.py reads this file and alerts when a job has no ok for 48 hours.
#
# The Python twin is src/foreclosure_scraper/job_events.py; both write the same
# shape. Outcomes: ok, no_change, skipped_lock, skipped_memory, failed, push_failed.
#
# Nothing here may fail the job: every write is best-effort.

JOB_EVENT_JOB=""
JOB_EVENT_START=0
JOB_EVENT_SWAP0=""
JOB_EVENT_DONE=0
JOB_EVENT_RSS_MB=""
JOB_RUN_RC=0

_je_root() { printf '%s' "${JOB_EVENT_ROOT:-${ROOT:-.}}"; }
_je_file() { printf '%s' "${JOB_EVENTS_FILE:-$(_je_root)/logs/job_events.jsonl}"; }
_je_ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
_je_iso() { date -u -r "$1" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null; }
# Strip anything that could break a hand-built JSON string.
_je_esc() { printf '%s' "$1" | tr -d '"\\' | tr '\n\r\t' '   ' | tr -d '\000-\010\013\014\016-\037' | cut -c1-200; }

_je_write() {
  _jw_f=$(_je_file)
  mkdir -p "$(dirname "$_jw_f")" 2>/dev/null || return 0
  if [ -f "$_jw_f" ] && [ "$(wc -c < "$_jw_f" 2>/dev/null || echo 0)" -gt "${JOB_EVENTS_MAX_BYTES:-5242880}" ]; then
    mv -f "$_jw_f" "$_jw_f.1" 2>/dev/null
  fi
  printf '%s\n' "$1" >> "$_jw_f" 2>/dev/null
  return 0
}

# Cumulative swap-outs since boot, in pages (vm_stat). Empty when unknown.
job_event_swapouts() {
  if [ -n "${JOB_EVENTS_FAKE_SWAPOUTS:-}" ]; then printf '%s' "$JOB_EVENTS_FAKE_SWAPOUTS"; return 0; fi
  vm_stat 2>/dev/null | awk '/^Swapouts:/ { gsub(/\./, "", $2); print $2; exit }'
}

_je_pagesize() {
  vm_stat 2>/dev/null | awk '/page size of/ { for (i = 1; i <= NF; i++) if ($i == "of") { print $(i + 1); exit } }'
}

# job_event_begin <job> [root]
job_event_begin() {
  JOB_EVENT_JOB="$1"
  [ -n "${2:-}" ] && JOB_EVENT_ROOT="$2"
  JOB_EVENT_START=$(date +%s)
  JOB_EVENT_SWAP0=$(job_event_swapouts)
  JOB_EVENT_DONE=0
  JOB_EVENT_RSS_MB=""
  return 0
}

# job_event_end <outcome> [rows_changed] [note]
# Writes the job's one line. Idempotent: a second call in the same job is ignored,
# so the EXIT trap (job_event_finalize) never double-reports.
job_event_end() {
  [ "${JOB_EVENT_DONE:-0}" = "1" ] && return 0
  JOB_EVENT_DONE=1
  _je_outcome="${1:-failed}"
  case "$_je_outcome" in
    ok|no_change|skipped_lock|skipped_memory|failed|push_failed) ;;
    *) _je_outcome="failed" ;;
  esac
  _je_rows="${2:-}"
  _je_note="${3:-}"
  _je_end=$(date +%s)
  _je_dur=$(( _je_end - ${JOB_EVENT_START:-_je_end} ))
  _je_line="{\"ts\":\"$(_je_iso "$_je_end")\",\"kind\":\"job\",\"job\":\"$(_je_esc "${JOB_EVENT_JOB:-unknown}")\""
  if [ "${JOB_EVENT_START:-0}" -gt 0 ]; then
    _je_line="$_je_line,\"start\":\"$(_je_iso "$JOB_EVENT_START")\""
  fi
  _je_line="$_je_line,\"end\":\"$(_je_iso "$_je_end")\",\"outcome\":\"$_je_outcome\""
  case "$_je_rows" in
    ''|*[!0-9]*) _je_line="$_je_line,\"rows_changed\":null" ;;
    *) _je_line="$_je_line,\"rows_changed\":$_je_rows" ;;
  esac
  _je_line="$_je_line,\"duration_s\":$_je_dur,\"pid\":$$"
  _je_swap1=$(job_event_swapouts)
  if [ -n "${JOB_EVENT_SWAP0:-}" ] && [ -n "$_je_swap1" ]; then
    _je_psz=$(_je_pagesize); _je_psz=${_je_psz:-16384}
    _je_mb=$(awk -v a="$JOB_EVENT_SWAP0" -v b="$_je_swap1" -v p="$_je_psz" 'BEGIN { printf "%.1f", (b - a) * p / 1048576 }')
    _je_line="$_je_line,\"swapouts_start\":$JOB_EVENT_SWAP0,\"swapouts_end\":$_je_swap1,\"swap_out_mb\":$_je_mb"
  fi
  [ -n "${JOB_EVENT_RSS_MB:-}" ] && _je_line="$_je_line,\"rss_peak_mb\":$JOB_EVENT_RSS_MB"
  [ -n "$_je_note" ] && _je_line="$_je_line,\"note\":\"$(_je_esc "$_je_note")\""
  _je_write "$_je_line}"
  return 0
}

# job_event_finalize — call from an EXIT trap. A job that reached its end without
# reporting an outcome (killed, crashed, set -e style exit) is recorded as failed.
job_event_finalize() {
  _jf_rc=$?
  [ "${JOB_EVENT_DONE:-0}" = "1" ] && return 0
  [ -n "${JOB_EVENT_JOB:-}" ] || return 0
  job_event_end failed "" "exited_without_outcome rc=$_jf_rc"
  return 0
}

# job_event_note <event> [key=value ...] — a non-outcome line (lock break, gate wait).
job_event_note() {
  _jn_event="$1"; shift
  _jn_pid=$$
  _jn_body=""
  for _jn_kv in "$@"; do
    _jn_k=${_jn_kv%%=*}
    _jn_v=${_jn_kv#*=}
    _jn_body="$_jn_body,\"$(_je_esc "$_jn_k")\":\"$(_je_esc "$_jn_v")\""
  done
  _je_write "{\"ts\":\"$(_je_ts)\",\"kind\":\"note\",\"event\":\"$(_je_esc "$_jn_event")\",\"pid\":$_jn_pid$_jn_body}"
  return 0
}

# job_run <timeout-seconds> <command...>
#
# Runs a command with a hard timeout and measures its peak RSS. macOS has no
# timeout(1) or gtimeout, so the timeout is scripts/run_timeout.pl (perl ships with
# macOS). Exit status is the command's, or 124 on timeout, and lands in
# JOB_RUN_RC; the peak RSS in MiB lands in JOB_EVENT_RSS_MB for job_event_end.
job_run() {
  _jr_secs="$1"; shift
  _jr_tmp="${TMPDIR:-/tmp}/job_run.$$.rusage"
  _jr_pl="$(_je_root)/scripts/run_timeout.pl"
  if [ -x /usr/bin/time ] && [ -f "$_jr_pl" ]; then
    /usr/bin/time -l -o "$_jr_tmp" /usr/bin/perl "$_jr_pl" "$_jr_secs" "$@"
    JOB_RUN_RC=$?
    _jr_rss=$(awk '/maximum resident set size/ { printf "%d", $1 / 1048576; exit }' "$_jr_tmp" 2>/dev/null)
    [ -n "$_jr_rss" ] && JOB_EVENT_RSS_MB="$_jr_rss"
    rm -f "$_jr_tmp"
  elif [ -f "$_jr_pl" ]; then
    /usr/bin/perl "$_jr_pl" "$_jr_secs" "$@"
    JOB_RUN_RC=$?
  else
    "$@"
    JOB_RUN_RC=$?
  fi
  return $JOB_RUN_RC
}
