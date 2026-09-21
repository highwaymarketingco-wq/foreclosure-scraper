#!/bin/zsh
# Weekly parcel-cache refresh — bulk re-download every configured county's parcel
# layer into local SQLite (completeness-verified, overwrite-in-place). Runs of the
# foreclosure engine just READ the cache via parcel_cache.lookup(); this is the only
# job that hits the county GIS in bulk. Parcels are slow-moving, so weekly is plenty.
#
# Overwrite-in-place = constant disk (no growth, no cleanup needed). A truncated
# download is REJECTED (never replaces a good cache). It touches only
# data/parcel_cache, so it takes no board lock, but it IS a memory hog: it runs the
# memory gate (audit O9) and records swap-out delta and peak RSS in
# logs/job_events.jsonl. The exit status of the python step is propagated (it was
# not: a failed refresh printed nothing anywhere anyone looked).
set -uo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
ROOT="${FORECLOSURE_ROOT:-$HOME/foreclosure-scraper}"
cd "$ROOT" || exit 1
mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/parcel_cache_refresh.log"    # was /tmp (audit O10)
exec >> "$LOG" 2>&1
STAMP=$(date +%Y%m%dT%H%M%S)
echo "==> parcel-cache refresh $STAMP"

. "$ROOT/scripts/job_event.sh"
. "$ROOT/scripts/board_lock.sh"
JOB_EVENT_ROOT="$ROOT"
job_event_begin parcelcache
trap 'job_event_finalize' EXIT INT TERM

PY="$ROOT/.venv/bin/python"     # the project venv directly; no uv sync can touch it
if [ ! -x "$PY" ]; then
  echo "!! $PY missing"; job_event_end failed "" "venv_missing"; exit 127
fi

_blroot="$ROOT"
board_mem_gate parcelcache || {
  echo "memory gate refused ($BOARD_MEM_REASON) - skipping this run"
  job_event_end skipped_memory "" "$BOARD_MEM_REASON"; exit 0
}

job_run "${PARCELCACHE_TIMEOUT:-7200}" "$PY" scripts/refresh_parcel_cache.py
RC=$JOB_RUN_RC
echo "==> parcel-cache refresh done $(date)  rc=$RC  size=$(du -sh data/parcel_cache 2>/dev/null | cut -f1)"
if [ "$RC" -ne 0 ]; then
  job_event_end failed "" "rc=$RC"; exit 1
fi
job_event_end ok
