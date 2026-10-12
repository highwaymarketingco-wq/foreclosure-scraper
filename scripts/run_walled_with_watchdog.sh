#!/bin/bash
# Wrapper: runs run_walled_sources.py under the memory watchdog.
#
# The watchdog (deploy/oracle/mem_watchdog.py) monitors RSS+swap of the
# process tree and kills it CLEANLY before the kernel's OOM killer would.
# A clean kill lets the resumable manifest pick up where it left off next
# run — every scraper's output is already written to data/walled_output/.
#
# Usage: bash scripts/run_walled_with_watchdog.sh
#
# Exit codes:
#   0  — runner completed normally
#   9  — watchdog killed the runner (memory threshold hit). Re-run to resume.
#   1  — other error

set -euo pipefail

cd "$(dirname "$0")/.."

# Ensure environment
export PYTHONPATH="src:.venv/lib/python3.12/site-packages"
export BOARD_LOAD_ALLOW_LARGE=1
export BOARD_LOCK_BYPASS=1
export SC_PUBLIC_INDEX_BATCH_SIZE=4
export TYLER_USE_WAF_SOLVER=1
export DISPLAY=:99

# Start the runner in the background
.venv/bin/python3.12 scripts/run_walled_sources.py &
RUNNER_PID=$!
echo "[watchdog-wrapper] Runner started: PID $RUNNER_PID"

# Start the memory watchdog in the background
# Kill thresholds: 20GB tree RSS+swap, or MemAvailable < 500MB with SwapFree < 300MB
# (conservative — the VM has 24GB RAM, and we want to kill BEFORE the kernel does)
.venv/bin/python3.12 deploy/oracle/mem_watchdog.py \
    --pid "$RUNNER_PID" \
    --log "data/walled_run_memwatch.log" \
    --interval 5 \
    --kill-total-mb 20480 \
    --kill-avail-mb 500 \
    --kill-swapfree-mb 300 &
WATCHDOG_PID=$!
echo "[watchdog-wrapper] Watchdog started: PID $WATCHDOG_PID"

# Wait for the runner to finish
wait "$RUNNER_PID"
RUNNER_EXIT=$?

# Stop the watchdog (it would exit on its own, but let's be clean)
kill "$WATCHDOG_PID" 2>/dev/null || true
wait "$WATCHDOG_PID" 2>/dev/null || true

# Check if the watchdog killed the runner
if [ "$RUNNER_EXIT" -eq 137 ] || [ "$RUNNER_EXIT" -eq 9 ]; then
    echo "[watchdog-wrapper] ⚠️  Runner was KILLED by memory watchdog (exit $RUNNER_EXIT)"
    echo "[watchdog-wrapper] Memory log: data/walled_run_memwatch.log"
    echo "[watchdog-wrapper] Re-run this script to resume from where it left off."
    echo "[watchdog-wrapper] Completed scrapers will be skipped (resumable manifest)."
    exit 9
fi

if [ "$RUNNER_EXIT" -eq 0 ]; then
    echo "[watchdog-wrapper] ✅ Runner completed successfully"
else
    echo "[watchdog-wrapper] ❌ Runner exited with code $RUNNER_EXIT"
fi

exit "$RUNNER_EXIT"
