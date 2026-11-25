#!/usr/bin/env bash
# Self-looping comps/comps_tight backfill sweep (2026-11-11).
#
# Cycles backfill_comps.py across the biggest known gaps plus a periodic
# no-filter pass that sweeps board order for the rest. UPDATED 2026-11-25:
# the original three (Mecklenburg, Wake, Buncombe -- 57,151 comps_tight rows
# combined, per docs/gap_matrix/low_yield_queue.md, itself generated from the
# 2026-11-04 gap list) were stale -- a fresh gap_matrix run same day found
# York (80,660 comps_tight rows) and Spartanburg (39,001) each bigger than
# any single one of the original three, and together more than double all
# three combined. Added both rather than replacing the original three, since
# nothing here suggested Mecklenburg/Wake/Buncombe stopped being real gaps,
# just that they're no longer the ONLY big ones. Re-check docs/gap_matrix's
# freshest gap_list before assuming this 5-county set is still current.
#
# NO `|| break` ANYWHERE -- a bare BoardLockBusy exit (code 1, this board has
# many concurrent writers tonight) must not kill the loop; it just means this
# iteration's live-fetched comps were not written and will be re-fetched next
# time that county comes up. Only a real crash would show as a python
# traceback in the log, and even that does not stop the next iteration --
# that is the whole point of this wrapper over a single long-running
# invocation (see backfill_comps.py's own board_lock-narrowing fix for why a
# single invocation would otherwise hold resources across an unbounded
# network wait).
#
# Usage: bash scripts/run_comps_sweep.sh   (run detached: see the nohup line
# this project's launch convention uses, e.g.
#   nohup bash scripts/run_comps_sweep.sh < /dev/null > /dev/null 2>&1 & disown
# )
set -u
cd "$(dirname "$0")/.."

PY=".venv/bin/python3.12"
LOG="logs/comps_sweep_$(date +%Y%m%d).log"
MAX_ROWS=1500
ITERATIONS=400

mkdir -p logs

COUNTIES=("Mecklenburg:NC" "Wake:NC" "Buncombe:NC" "York:SC" "Spartanburg:SC" "")

i=0
while [ "$i" -lt "$ITERATIONS" ]; do
  idx=$(( i % ${#COUNTIES[@]} ))
  c="${COUNTIES[$idx]}"
  ts="$(date -u +%FT%TZ)"
  if [ -z "$c" ]; then
    echo "=== $ts iter=$i sweep (no county filter, board order) ===" >> "$LOG"
    BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 "$PY" scripts/backfill_comps.py --max-rows "$MAX_ROWS" >> "$LOG" 2>&1
  else
    echo "=== $ts iter=$i county=$c ===" >> "$LOG"
    BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 "$PY" scripts/backfill_comps.py --counties "$c" --max-rows "$MAX_ROWS" >> "$LOG" 2>&1
  fi
  i=$((i + 1))
  sleep 15
done

echo "=== $(date -u +%FT%TZ) run_comps_sweep.sh: $ITERATIONS iterations done ===" >> "$LOG"
