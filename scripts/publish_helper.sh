#!/bin/sh
# The reusable publish helper: COMMIT inside the board lock, RELEASE it, then PUSH.
# Source this; do not execute it. Needs job_event.sh, board_lock.sh and
# board_payload.sh sourced first (in that order).
#
#   publish_commit "$ROOT" "commit message" [any|payload]   # inside the lock
#   board_lock_release                                      # ...then let go
#   publish_push "$ROOT"                                    # outside the lock
#
# WHY (audit O7). Every publisher ran `git push` INSIDE the board lock with no
# timeout. One publish is 118 to 172 MB; on 2026-09-20 the pushes failed with
# "unexpected disconnect while reading sideband packet" and "Could not resolve
# host". A stalled push therefore held the lock for as long as git chose to wait,
# and every other scheduled job skipped with exit 0. The lock exists to protect
# the load -> mutate -> write -> COMMIT span. A push touches no working-tree file
# (the commit already froze the content), so it does not need the lock.
#
# What does need the lock is a rebase onto a moved origin/main: it rewrites the
# working tree, so publish_push briefly RE-ACQUIRES the lock for exactly that step
# (waits up to PUBLISH_REBASE_WAIT seconds, default 600) and releases it again
# before the push.
#
# Everything is bounded by scripts/run_timeout.pl (macOS has no timeout(1)):
#   fetch  PUBLISH_FETCH_TIMEOUT  default 300 s
#   push   PUBLISH_PUSH_TIMEOUT   default 900 s   (`timeout 900` as specified)
#   tries  PUBLISH_PUSH_ATTEMPTS  default 3, with 30 s, 90 s back-off
# and git itself is told to abandon a stalled transfer (http.lowSpeedLimit 1000 B/s
# for http.lowSpeedTime 120 s, set in the repo's LOCAL config by publish_git_config).

PUBLISH_PUSH_OUT=""
PUBLISH_COMMIT_RESULT=""

publish_git_config() {   # <repo-root> — idempotent, LOCAL config only
  git -C "$1" config --local http.lowSpeedLimit "${PUBLISH_LOW_SPEED_LIMIT:-1000}" 2>/dev/null
  git -C "$1" config --local http.lowSpeedTime "${PUBLISH_LOW_SPEED_TIME:-120}" 2>/dev/null
  return 0
}

_publish_timeout() {   # <seconds> <command...>
  _pt_secs="$1"; shift
  _pt_pl="${PUBLISH_ROOT:-.}/scripts/run_timeout.pl"
  if [ -f "$_pt_pl" ]; then
    /usr/bin/perl "$_pt_pl" "$_pt_secs" "$@"
  else
    "$@"
  fi
}

# publish_commit <repo-root> <message> [any|payload]
#   any      commit when ANYTHING staged changed (lrcpwa, run_local)
#   payload  commit only when a payload file other than run_meta.json changed, and
#            `git reset -q` otherwise (sos_agent: a walled run rewrites the board
#            byte-identically and must not create an empty commit)
# Returns 0 committed, 1 nothing to commit, 2 the commit failed (a pre-commit hook,
# e.g. the 95 MiB size gate, refused it) or the staged board was not a consistent part set
# (stage_failed, parts_inconsistent). PUBLISH_COMMIT_RESULT names which.
publish_commit() {
  PUBLISH_ROOT="$1"
  _pc_msg="$2"
  _pc_mode="${3:-any}"
  publish_git_config "$PUBLISH_ROOT"
  board_payload_check "$PUBLISH_ROOT" || true   # loud, non-fatal: see board_payload.sh
  if ! board_payload_add "$PUBLISH_ROOT"; then
    # the board parts could not all be staged: the whole board payload was unstaged
    git -C "$PUBLISH_ROOT" reset -q
    PUBLISH_COMMIT_RESULT="stage_failed"
    return 2
  fi
  if ! board_payload_verify_staged "$PUBLISH_ROOT"; then
    # staged parts are not the set the staged manifest lists (audit O1): never commit that
    git -C "$PUBLISH_ROOT" reset -q
    PUBLISH_COMMIT_RESULT="parts_inconsistent"
    return 2
  fi
  _pc_has=1
  if [ "$_pc_mode" = "payload" ]; then
    board_payload_changed "$PUBLISH_ROOT" && _pc_has=0
  else
    git -C "$PUBLISH_ROOT" diff --cached --quiet || _pc_has=0
  fi
  if [ "$_pc_has" != "0" ]; then
    [ "$_pc_mode" = "payload" ] && git -C "$PUBLISH_ROOT" reset -q
    PUBLISH_COMMIT_RESULT="nothing_to_commit"
    return 1
  fi
  if git -C "$PUBLISH_ROOT" commit -q -m "$_pc_msg"; then
    PUBLISH_COMMIT_RESULT="committed"
    return 0
  fi
  PUBLISH_COMMIT_RESULT="commit_failed"
  return 2
}

# _publish_behind <root> — number of commits origin/main has that HEAD lacks
_publish_behind() {
  git -C "$1" rev-list --count HEAD..origin/main 2>/dev/null || echo 0
}

# publish_push <repo-root> [attempts]
# 0 = pushed, 1 = every attempt failed (the commit stays local; the NEXT publisher's
# push carries it). PUBLISH_PUSH_OUT holds the tail of git's output for the log.
publish_push() {
  PUBLISH_ROOT="$1"
  _pp_n="${2:-${PUBLISH_PUSH_ATTEMPTS:-3}}"
  _pp_i=1
  publish_git_config "$PUBLISH_ROOT"
  while [ "$_pp_i" -le "$_pp_n" ]; do
    if _publish_timeout "${PUBLISH_FETCH_TIMEOUT:-300}" git -C "$PUBLISH_ROOT" fetch -q origin main >/dev/null 2>&1; then
      if [ "$(_publish_behind "$PUBLISH_ROOT")" -gt 0 ]; then
        # main moved. The rebase rewrites the working tree, so it needs the lock.
        if board_lock_acquire "$PUBLISH_ROOT" "publish_rebase" "${PUBLISH_REBASE_WAIT:-600}" 1800; then
          git -C "$PUBLISH_ROOT" rebase --autostash origin/main >/dev/null 2>&1 \
            || { git -C "$PUBLISH_ROOT" rebase --abort >/dev/null 2>&1; PUBLISH_PUSH_OUT="rebase onto origin/main failed"; }
          board_lock_release
        else
          PUBLISH_PUSH_OUT="could not take the board lock to rebase ($(board_lock_holder))"
        fi
      fi
    fi
    if PUBLISH_PUSH_OUT=$(_publish_timeout "${PUBLISH_PUSH_TIMEOUT:-900}" git -C "$PUBLISH_ROOT" push origin main 2>&1); then
      return 0
    fi
    PUBLISH_PUSH_OUT=$(printf '%s\n' "$PUBLISH_PUSH_OUT" | tail -3)
    if [ "$_pp_i" -lt "$_pp_n" ]; then
      sleep $(( ${PUBLISH_BACKOFF_BASE:-30} * (_pp_i * _pp_i + _pp_i) / 2 ))   # 30, 90, 180 s
    fi
    _pp_i=$(( _pp_i + 1 ))
  done
  return 1
}
