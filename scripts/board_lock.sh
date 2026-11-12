#!/bin/sh
# THE BOARD LOCK, shell side. Source this; do not execute it.
#
#   . "$ROOT/scripts/board_lock.sh"
#   board_lock_acquire "$ROOT" "lrcpwa_refresh" 0 3600 || { echo "busy"; exit 0; }
#   trap 'board_lock_release' EXIT INT TERM
#   ... load_board -> mutate -> write_artifact ...
#
# WHY THIS EXISTS. The critical section is `load_board -> mutate ->
# write_artifact` and it runs for minutes to hours. Every guard here before was
# a pgrep taken BEFORE that span opened, which is TOCTOU-racy by construction: a
# check that happens before the section can always lose to a writer that starts
# after it. On 2026-08-10 the noon lrcpwa pass (1,064 parcels resolved, 343
# county values, 410 absentee tags) was silently reverted by the 09:30 vision
# job writing back a board it had loaded at 09:33.
#
# WHY NOT shlock. /usr/bin/shlock is present on macOS and it does NOT break
# stale locks. Measured on this machine (shell_cmds-326, macOS 25.1) against a
# lock whose owner PID was genuinely dead:
#     shlock: process 4514 is dead 4514
#     shlock: lock time changed 1786455189 >= 0        -> exit 1
# Repeated invocations give the same answer, so one killed run would have
# stopped every scheduled job forever. flock(1) does not exist on macOS at all.
#
# THE PROTOCOL is implemented TWICE — here and in
# src/foreclosure_scraper/web_artifact.py board_lock() — so that a shell wrapper
# and a Python board-writer contend for the SAME lock. The full description
# lives in that file's THE BOARD LOCK block. In short:
#   lock      = the DIRECTORY <repo>/logs/.board.lock (mkdir is atomic)
#   ownership = <lock>/pid, six lines: pid, owner label, start epoch, heartbeat
#               epoch, max runtime (s), token. Old readers read lines 1 and 2.
#   children  = <lock>/children/<pid>: a writer running INSIDE the lock registers
#               itself, so the lock outlives a killed wrapper (audit O11)
#   stale     = owner AND all children dead, OR a live holder older than its max
#               runtime + 30 minutes (a hung holder with a live PID no longer
#               blocks every job forever). Breaks and skips are logged as job
#               events.
#   break     = mv the directory aside (atomic: one racer wins), then rm -rf
#   reentrant = FORECLOSURE_BOARD_LOCK_HELD is exported to children, so a
#               wrapper holding the lock can run a Python writer that also asks
#               for it. The child sees its own path and proceeds without
#               acquiring, and never releases what it did not take.
#   fence     = FORECLOSURE_BOARD_LOCK_TOKEN is exported too; write_artifact
#               refuses if the token on disk is no longer the caller's, which is
#               what stops a hung holder whose lock was broken from writing.
#   gate      = before taking the lock, a MEMORY GATE (audit O9): swap used above
#               3 GB or free+inactive below 1 GB. BOARD_MEM_GATE=warn (default:
#               log a job event, proceed) | enforce (wait BOARD_MEM_GATE_WAIT, 900 s,
#               then refuse) | off. See board_mem_gate for why warn is the default.
#
# RETURN CODES of board_lock_acquire:
#   0  yours (or an ancestor already holds it)
#   1  a live writer has it            (BOARD_LOCK_REFUSAL=busy)
#   2  the memory gate refused          (BOARD_LOCK_REFUSAL=memory)
#
# tests/test_publish_plumbing.py drives this file and the Python implementation
# against each other. Changing one side alone will fail that test, which is the
# point: a lock that two processes disagree about is not a lock.

BOARD_LOCK_DIR=""
BOARD_LOCK_REENTRANT=0
BOARD_LOCK_HB_PID=""
BOARD_LOCK_TOKEN=""
BOARD_LOCK_REFUSAL=""
BOARD_LOCK_STALE_GRACE=1800

board_lock_path() {
  printf '%s/logs/.board.lock' "$1"
}

# read one line of the pid file
_bl_line() { sed -n "$2p" "$1/pid" 2>/dev/null; }

_bl_now() { date +%s; }

_bl_write_info() {   # dir pid owner start heartbeat maxrt token
  printf '%s\n%s\n%s\n%s\n%s\n%s\n' "$2" "$3" "$4" "$5" "$6" "$7" > "$1/pid.$$.tmp" 2>/dev/null \
    && mv -f "$1/pid.$$.tmp" "$1/pid" 2>/dev/null
}

# best-effort job event; job_event.sh is sourced on first use
_bl_note() {
  if ! type job_event_note >/dev/null 2>&1; then
    [ -f "${_blroot:-.}/scripts/job_event.sh" ] && . "${_blroot:-.}/scripts/job_event.sh"
  fi
  type job_event_note >/dev/null 2>&1 && JOB_EVENT_ROOT="${_blroot:-.}" job_event_note "$@"
  return 0
}

_bl_mtime() {
  stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null
}

# _bl_stale_reason <lockdir> — prints dead_owner | expired | unreadable, or nothing
# when the lock is healthy.
_bl_stale_reason() {
  _bsd="$1"
  _bspid=$(_bl_line "$_bsd" 1)
  if [ -z "$_bspid" ]; then printf 'unreadable'; return 0; fi
  _bsalive=0
  kill -0 "$_bspid" 2>/dev/null && _bsalive=1
  if [ "$_bsalive" = "0" ] && [ -d "$_bsd/children" ]; then
    for _bsc in "$_bsd"/children/*; do
      [ -e "$_bsc" ] || continue
      _bscp=${_bsc##*/}
      if kill -0 "$_bscp" 2>/dev/null; then _bsalive=1; else rm -f "$_bsc" 2>/dev/null; fi
    done
  fi
  if [ "$_bsalive" = "0" ]; then printf 'dead_owner'; return 0; fi
  _bsstart=$(_bl_line "$_bsd" 3)
  [ -n "$_bsstart" ] || _bsstart=$(_bl_mtime "$_bsd/pid")
  _bsmax=$(_bl_line "$_bsd" 5)
  [ -n "$_bsmax" ] || _bsmax="${BOARD_LOCK_DEFAULT_MAX_RUNTIME:-21600}"
  if [ -n "$_bsstart" ]; then
    _bsage=$(( $(_bl_now) - _bsstart ))
    if [ "$_bsage" -gt $(( _bsmax + BOARD_LOCK_STALE_GRACE )) ]; then printf 'expired'; return 0; fi
  fi
  return 0
}

# ---------------------------------------------------------------------------
# THE MEMORY GATE (audit O9)
#
# board_mem_probe sets BOARD_MEM_SWAP_MB (swap used), BOARD_MEM_FREE_MB (free +
# inactive) and BOARD_MEM_REASON (empty when the gate would pass).
# Test hooks BOARD_GATE_FAKE_SWAP_MB / BOARD_GATE_FAKE_FREE_MB stand in for the
# machine. A probe that cannot read the machine reads as healthy.
# ---------------------------------------------------------------------------
board_mem_probe() {
  BOARD_MEM_SWAP_MB=""; BOARD_MEM_FREE_MB=""; BOARD_MEM_REASON=""
  if [ -n "${BOARD_GATE_FAKE_SWAP_MB:-}${BOARD_GATE_FAKE_FREE_MB:-}" ]; then
    BOARD_MEM_SWAP_MB="${BOARD_GATE_FAKE_SWAP_MB:-0}"
    BOARD_MEM_FREE_MB="${BOARD_GATE_FAKE_FREE_MB:-1000000}"
  else
    _bmo=$(sysctl -n vm.swapusage 2>/dev/null)
    BOARD_MEM_SWAP_MB=$(printf '%s' "$_bmo" | sed -n 's/.*used = \([0-9.]*\)M.*/\1/p')
    BOARD_MEM_FREE_MB=$(vm_stat 2>/dev/null | awk '
      /page size of/ { for (i = 1; i <= NF; i++) if ($i == "of") ps = $(i + 1) }
      /^Pages free/     { gsub(/\./, "", $3); f = $3 }
      /^Pages inactive/ { gsub(/\./, "", $3); n = $3 }
      END { if (ps > 0) printf "%d", (f + n) * ps / 1048576 }')
  fi
  _bmmax="${BOARD_GATE_SWAP_MB:-3072}"; _bmmin="${BOARD_GATE_FREE_MB:-1024}"
  if [ -n "$BOARD_MEM_SWAP_MB" ] && awk -v a="$BOARD_MEM_SWAP_MB" -v b="$_bmmax" 'BEGIN { exit !(a + 0 > b + 0) }'; then
    BOARD_MEM_REASON="swap_used_mb=$BOARD_MEM_SWAP_MB>$_bmmax"
  fi
  if [ -n "$BOARD_MEM_FREE_MB" ] && awk -v a="$BOARD_MEM_FREE_MB" -v b="$_bmmin" 'BEGIN { exit !(a + 0 < b + 0) }'; then
    BOARD_MEM_REASON="${BOARD_MEM_REASON:+$BOARD_MEM_REASON,}free_plus_inactive_mb=$BOARD_MEM_FREE_MB<$_bmmin"
  fi
  return 0
}

# board_mem_gate <owner>  — 0 to go, 2 to refuse.
#   BOARD_MEM_GATE=warn     (DEFAULT) log the pressure as a job event and proceed
#   BOARD_MEM_GATE=enforce  wait up to BOARD_MEM_GATE_WAIT s, then refuse (return 2)
#   BOARD_MEM_GATE=off      do not look
#
# WHY warn IS THE DEFAULT. Measured 2026-09-21 12:40 on this 8 GB Mac with ONE job
# running: swap used 7,015 MB (the audit saw 4,500 to 5,400 MB all morning). Against
# the 3,072 MB threshold that is a permanent refusal, so enforcing it by default would
# skip every scheduled job every day. Run in warn for a week, read the mem_gate lines
# in logs/job_events.jsonl to pick thresholds this machine can meet, then set
# BOARD_MEM_GATE=enforce in the launchd plists (deploy/mac/*.plist).
board_mem_gate() {
  _bgowner="${1:-shell}"
  _bgmode="${BOARD_MEM_GATE:-warn}"
  [ "$_bgmode" = "off" ] && return 0
  board_mem_probe
  [ -z "$BOARD_MEM_REASON" ] && return 0
  if [ "$_bgmode" = "warn" ]; then
    _bl_note mem_gate "owner=$_bgowner" "mode=warn" "action=proceed" "reason=$BOARD_MEM_REASON"
    return 0
  fi
  _bgwait="${BOARD_MEM_GATE_WAIT:-900}"
  _bgpoll="${BOARD_MEM_GATE_POLL:-30}"
  _bgt0=$(_bl_now)
  _bl_note mem_gate "owner=$_bgowner" "mode=enforce" "action=waiting" "reason=$BOARD_MEM_REASON"
  while :; do
    _bgel=$(( $(_bl_now) - _bgt0 ))
    if [ "$_bgel" -ge "$_bgwait" ]; then
      _bl_note mem_gate "owner=$_bgowner" "mode=enforce" "action=refused" "reason=$BOARD_MEM_REASON" "waited_s=$_bgel"
      return 2
    fi
    sleep "$_bgpoll"
    board_mem_probe
    if [ -z "$BOARD_MEM_REASON" ]; then
      _bl_note mem_gate "owner=$_bgowner" "mode=enforce" "action=cleared" "waited_s=$(( $(_bl_now) - _bgt0 ))"
      return 0
    fi
  done
}

# ---------------------------------------------------------------------------
# heartbeat: a background subshell re-stamps line 4 of the pid file every
# BOARD_LOCK_HEARTBEAT_S (60) seconds while the owner lives. Diagnostic only;
# staleness is decided by liveness and max runtime, not by a quiet heartbeat.
# ---------------------------------------------------------------------------
_bl_heartbeat_start() {   # dir owner-pid owner-label start maxrt token
  (
    _hbdir="$1"; _hbpid="$2"; _hbown="$3"; _hbstart="$4"; _hbmax="$5"; _hbtok="$6"
    while :; do
      sleep "${BOARD_LOCK_HEARTBEAT_S:-60}"
      kill -0 "$_hbpid" 2>/dev/null || exit 0
      [ "$(_bl_line "$_hbdir" 6)" = "$_hbtok" ] || exit 0
      _bl_write_info "$_hbdir" "$_hbpid" "$_hbown" "$_hbstart" "$(_bl_now)" "$_hbmax" "$_hbtok"
    done
  ) >/dev/null 2>&1 </dev/null &
  BOARD_LOCK_HB_PID=$!
}

# board_lock_acquire <repo-root> [owner-label] [wait-seconds] [max-runtime-seconds]
board_lock_acquire() {
  _blroot="$1"
  _blowner="${2:-shell}"
  _blwait="${3:-0}"
  _blmax="${4:-${BOARD_LOCK_MAX_RUNTIME:-${BOARD_LOCK_DEFAULT_MAX_RUNTIME:-21600}}}"
  BOARD_LOCK_DIR="$(board_lock_path "$_blroot")"
  BOARD_LOCK_REFUSAL=""

  if [ "${FORECLOSURE_BOARD_LOCK_HELD:-}" = "$BOARD_LOCK_DIR" ]; then
    BOARD_LOCK_REENTRANT=1
    # The lock this process inherited may have been broken as stale and re-taken
    # by another job; if so, proceeding would put two writers on the board.
    if [ -n "${FORECLOSURE_BOARD_LOCK_TOKEN:-}" ] \
       && [ "$(_bl_line "$BOARD_LOCK_DIR" 6)" != "$FORECLOSURE_BOARD_LOCK_TOKEN" ]; then
      BOARD_LOCK_REENTRANT=0
      BOARD_LOCK_DIR=""
      BOARD_LOCK_REFUSAL="lost"
      return 1
    fi
    # register this shell as a live holder inside the ancestor's lock
    if [ -d "$BOARD_LOCK_DIR" ]; then
      mkdir -p "$BOARD_LOCK_DIR/children" 2>/dev/null
      printf '%s\n' "$_blowner" > "$BOARD_LOCK_DIR/children/$$" 2>/dev/null
    fi
    return 0
  fi

  mkdir -p "$_blroot/logs" 2>/dev/null || true

  board_mem_gate "$_blowner" || { BOARD_LOCK_DIR=""; BOARD_LOCK_REFUSAL="memory"; return 2; }

  _blend=$(( $(date +%s) + _blwait ))
  BOARD_LOCK_TOKEN="$$.$(date +%s).$RANDOM$RANDOM"
  while :; do
    if mkdir "$BOARD_LOCK_DIR" 2>/dev/null; then
      _blstart=$(_bl_now)
      _bl_write_info "$BOARD_LOCK_DIR" "$$" "$_blowner" "$_blstart" "$_blstart" "$_blmax" "$BOARD_LOCK_TOKEN"
      FORECLOSURE_BOARD_LOCK_HELD="$BOARD_LOCK_DIR"
      FORECLOSURE_BOARD_LOCK_TOKEN="$BOARD_LOCK_TOKEN"
      export FORECLOSURE_BOARD_LOCK_HELD FORECLOSURE_BOARD_LOCK_TOKEN
      BOARD_LOCK_REENTRANT=0
      _bl_heartbeat_start "$BOARD_LOCK_DIR" "$$" "$_blowner" "$_blstart" "$_blmax" "$BOARD_LOCK_TOKEN"
      return 0
    fi

    _blholder=$(_bl_line "$BOARD_LOCK_DIR" 1)
    if [ -z "$_blholder" ]; then
      # Either 20 microseconds old (the window between mkdir and the pid write)
      # or wreckage. Look again once before calling it wreckage.
      sleep 1
      _blholder=$(_bl_line "$BOARD_LOCK_DIR" 1)
    fi

    _blreason=$(_bl_stale_reason "$BOARD_LOCK_DIR")
    if [ -z "$_blreason" ]; then
      BOARD_LOCK_OWNER_PID="$_blholder"
      BOARD_LOCK_OWNER_LABEL=$(_bl_line "$BOARD_LOCK_DIR" 2)
      if [ "$(date +%s)" -ge "$_blend" ]; then
        _bl_hb=$(_bl_line "$BOARD_LOCK_DIR" 4)
        _bl_st=$(_bl_line "$BOARD_LOCK_DIR" 3)
        [ -n "$_bl_st" ] || _bl_st=$(_bl_mtime "$BOARD_LOCK_DIR/pid")   # a legacy 2-line lock has no start line
        _bl_note lock_skip "owner=$_blowner" "holder=$BOARD_LOCK_OWNER_LABEL" "holder_pid=$BOARD_LOCK_OWNER_PID" \
          "held_s=$(( $(_bl_now) - ${_bl_st:-$(_bl_now)} ))" "heartbeat_age_s=$(( $(_bl_now) - ${_bl_hb:-$(_bl_now)} ))"
        BOARD_LOCK_DIR=""
        BOARD_LOCK_TOKEN=""
        BOARD_LOCK_REFUSAL="busy"
        return 1
      fi
      sleep 5
      continue
    fi

    _bl_note lock_break "owner=$_blowner" "prior_owner=$(_bl_line "$BOARD_LOCK_DIR" 2)" "prior_pid=$_blholder" "reason=$_blreason"
    # Stale. mv is atomic, so exactly one racer gets the right to delete it.
    _blvictim="$BOARD_LOCK_DIR.stale.$$"
    rm -rf "$_blvictim" 2>/dev/null
    if mv "$BOARD_LOCK_DIR" "$_blvictim" 2>/dev/null; then
      rm -rf "$_blvictim" 2>/dev/null
    fi
  done
}

# board_lock_release — safe to call unconditionally from a trap.
board_lock_release() {
  if [ "$BOARD_LOCK_REENTRANT" = "1" ]; then
    # not ours; an ancestor holds it. Drop only our own registration.
    [ -n "$BOARD_LOCK_DIR" ] && rm -f "$BOARD_LOCK_DIR/children/$$" 2>/dev/null
    return 0
  fi
  [ -n "$BOARD_LOCK_DIR" ] || return 0
  # (wait inside a redirected group: otherwise the shell prints "Terminated: 15"
  # for the heartbeat job into the wrapper's log)
  [ -n "$BOARD_LOCK_HB_PID" ] && { kill "$BOARD_LOCK_HB_PID"; wait "$BOARD_LOCK_HB_PID"; } 2>/dev/null
  BOARD_LOCK_HB_PID=""
  # Only remove the lock if it is still OURS: an expired lock that another job broke
  # and re-took must not be deleted out from under it.
  if [ -z "$BOARD_LOCK_TOKEN" ] || [ "$(_bl_line "$BOARD_LOCK_DIR" 6)" = "$BOARD_LOCK_TOKEN" ] \
     || [ -z "$(_bl_line "$BOARD_LOCK_DIR" 1)" ]; then
    rm -rf "$BOARD_LOCK_DIR" 2>/dev/null
  fi
  BOARD_LOCK_DIR=""
  BOARD_LOCK_TOKEN=""
  unset FORECLOSURE_BOARD_LOCK_HELD FORECLOSURE_BOARD_LOCK_TOKEN
  return 0
}

# board_lock_holder — "<pid> <label>" for the writer that refused us, for logs.
board_lock_holder() {
  printf '%s %s' "${BOARD_LOCK_OWNER_PID:-?}" "${BOARD_LOCK_OWNER_LABEL:-unknown}"
}

# board_lock_refusal_message <what-we-skip> — one line for a wrapper's log, right
# for both refusal reasons.
board_lock_refusal_message() {
  case "$BOARD_LOCK_REFUSAL" in
    memory) printf 'memory gate refused (%s) - skipping %s' "${BOARD_MEM_REASON:-pressure}" "$1" ;;
    lost)   printf 'the inherited board lock was broken as stale - skipping %s' "$1" ;;
    *)      printf 'board-writer active (%s) - skipping %s' "$(board_lock_holder)" "$1" ;;
  esac
}
