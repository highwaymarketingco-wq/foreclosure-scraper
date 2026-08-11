#!/bin/sh
# THE BOARD LOCK, shell side. Source this; do not execute it.
#
#   . "$ROOT/scripts/board_lock.sh"
#   board_lock_acquire "$ROOT" "lrcpwa_refresh" || { echo "busy"; exit 0; }
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
#   ownership = <lock>/pid, two lines: "<pid>\n<owner label>\n"
#   stale     = pid unreadable after one 1s regrace, or kill -0 says dead
#   break     = mv the directory aside (atomic: one racer wins), then rm -rf
#   reentrant = FORECLOSURE_BOARD_LOCK_HELD is exported to children, so a
#               wrapper holding the lock can run a Python writer that also asks
#               for it. The child sees its own path and proceeds without
#               acquiring, and never releases what it did not take.
#
# tests/test_publish_plumbing.py drives this file and the Python implementation
# against each other. Changing one side alone will fail that test, which is the
# point: a lock that two processes disagree about is not a lock.

BOARD_LOCK_DIR=""
BOARD_LOCK_REENTRANT=0

board_lock_path() {
  printf '%s/logs/.board.lock' "$1"
}

# board_lock_acquire <repo-root> [owner-label] [wait-seconds]
# 0 = the lock is yours (or an ancestor already holds it); 1 = a live writer has it.
board_lock_acquire() {
  _blroot="$1"
  _blowner="${2:-shell}"
  _blwait="${3:-0}"
  BOARD_LOCK_DIR="$(board_lock_path "$_blroot")"

  if [ "${FORECLOSURE_BOARD_LOCK_HELD:-}" = "$BOARD_LOCK_DIR" ]; then
    BOARD_LOCK_REENTRANT=1
    return 0
  fi

  mkdir -p "$_blroot/logs" 2>/dev/null || true
  _blend=$(( $(date +%s) + _blwait ))
  while :; do
    if mkdir "$BOARD_LOCK_DIR" 2>/dev/null; then
      printf '%s\n%s\n' "$$" "$_blowner" > "$BOARD_LOCK_DIR/pid"
      FORECLOSURE_BOARD_LOCK_HELD="$BOARD_LOCK_DIR"
      export FORECLOSURE_BOARD_LOCK_HELD
      BOARD_LOCK_REENTRANT=0
      return 0
    fi

    _blholder=$(head -1 "$BOARD_LOCK_DIR/pid" 2>/dev/null)
    if [ -z "$_blholder" ]; then
      # Either 20 microseconds old (the window between mkdir and the pid write)
      # or wreckage. Look again once before calling it wreckage.
      sleep 1
      _blholder=$(head -1 "$BOARD_LOCK_DIR/pid" 2>/dev/null)
    fi

    if [ -n "$_blholder" ] && kill -0 "$_blholder" 2>/dev/null; then
      BOARD_LOCK_OWNER_PID="$_blholder"
      BOARD_LOCK_OWNER_LABEL=$(sed -n 2p "$BOARD_LOCK_DIR/pid" 2>/dev/null)
      if [ "$(date +%s)" -ge "$_blend" ]; then
        BOARD_LOCK_DIR=""
        return 1
      fi
      sleep 5
      continue
    fi

    # Stale. mv is atomic, so exactly one racer wins the right to delete it.
    _blvictim="$BOARD_LOCK_DIR.stale.$$"
    rm -rf "$_blvictim" 2>/dev/null
    if mv "$BOARD_LOCK_DIR" "$_blvictim" 2>/dev/null; then
      rm -rf "$_blvictim" 2>/dev/null
    fi
  done
}

# board_lock_release — safe to call unconditionally from a trap.
board_lock_release() {
  [ "$BOARD_LOCK_REENTRANT" = "1" ] && return 0   # not ours; an ancestor holds it
  [ -n "$BOARD_LOCK_DIR" ] || return 0
  rm -rf "$BOARD_LOCK_DIR" 2>/dev/null
  BOARD_LOCK_DIR=""
  unset FORECLOSURE_BOARD_LOCK_HELD
  return 0
}

# board_lock_holder — "<pid> <label>" for the writer that refused us, for logs.
board_lock_holder() {
  printf '%s %s' "${BOARD_LOCK_OWNER_PID:-?}" "${BOARD_LOCK_OWNER_LABEL:-unknown}"
}
