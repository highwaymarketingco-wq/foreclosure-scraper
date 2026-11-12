#!/usr/bin/env bash
# Self-looping comps/comps_tight backfill sweep (2026-11-11).
#
# Cycles backfill_comps.py across the three biggest known gaps (Mecklenburg,
# Wake, Buncombe -- 57,151 comps_tight rows between them, per
# docs/gap_matrix/low_yield_queue.md) plus a periodic no-filter pass that
# sweeps board order for the other ~146 counties' smaller gaps (149
# county-cells, 296,464 comps_tight rows total board-wide).
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

COUNTIES=("Mecklenburg:NC" "Wake:NC" "Buncombe:NC" "")

i=0
while [ "$i" -lt "$ITERATIONS" ]; do
  idx=$(( i % ${#COUNTIES[@]} ))
  c="${COUNTIES[$idx]}"
  ts="$(date -u +%FT%TZ)"
  if [ -z "$c" ]; then
    echo "=== $ts iter=$i sweep (no county filter, board order) ===" >> "$LOG"
    "$PY" scripts/backfill_comps.py --max-rows "$MAX_ROWS" >> "$LOG" 2>&1
  else
    echo "=== $ts iter=$i county=$c ===" >> "$LOG"
    "$PY" scripts/backfill_comps.py --counties "$c" --max-rows "$MAX_ROWS" >> "$LOG" 2>&1
  fi
  i=$((i + 1))
  sleep 15
done

echo "=== $(date -u +%FT%TZ) run_comps_sweep.sh: $ITERATIONS iterations done ===" >> "$LOG"
