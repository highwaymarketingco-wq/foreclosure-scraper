#!/bin/sh
# Run any command while holding the board lock.
#
#   scripts/with_board_lock.sh <owner> [--wait SECONDS] [--max-runtime SECONDS] -- <command...>
#   scripts/with_board_lock.sh enrich_board -- uv run python scripts/enrich_board.py
#
# WHY. write_artifact() now REFUSES to write the live board unless the process holds
# the board lock (audit O3). 54 board-writing scripts never took it themselves; this is
# how to run any of them without editing them. The lock is exported to the command
# (FORECLOSURE_BOARD_LOCK_HELD + a token), so a script that also asks for the lock
# proceeds inside this one, and a job event line is written when the command ends.
#
# Exit status: the command's, 75 when a live writer holds the lock, 76 when the memory
# gate refuses, 127 when uv is needed and missing.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"

OWNER="${1:-}"
[ -n "$OWNER" ] || { echo "usage: $0 <owner> [--wait S] [--max-runtime S] -- <command...>" >&2; exit 2; }
shift
WAIT=0; MAXRT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --wait) WAIT="$2"; shift 2 ;;
    --max-runtime) MAXRT="$2"; shift 2 ;;
    --) shift; break ;;
    *) echo "unexpected argument: $1 (put -- before the command)" >&2; exit 2 ;;
  esac
done
[ $# -gt 0 ] || { echo "no command given" >&2; exit 2; }
if [ "$1" = "uv" ]; then command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH ($PATH)" >&2; exit 127; }; fi

. "$ROOT/scripts/job_event.sh"
. "$ROOT/scripts/board_lock.sh"
JOB_EVENT_ROOT="$ROOT"
job_event_begin "$OWNER"
if ! board_lock_acquire "$ROOT" "$OWNER" "$WAIT" ${MAXRT:+"$MAXRT"}; then
  echo "$(board_lock_refusal_message "$OWNER")" >&2
  case "$BOARD_LOCK_REFUSAL" in memory) job_event_end skipped_memory "" "$BOARD_MEM_REASON"; exit 76 ;; esac
  job_event_end skipped_lock "" "$(board_lock_holder)"
  exit 75
fi
trap 'job_event_finalize; board_lock_release' EXIT INT TERM
cd "$ROOT" || exit 1
"$@"
RC=$?
if [ "$RC" -eq 0 ]; then job_event_end ok; else job_event_end failed "" "rc=$RC"; fi
exit $RC
