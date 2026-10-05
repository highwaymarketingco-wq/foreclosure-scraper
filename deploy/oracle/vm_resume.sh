#!/usr/bin/env bash
# Finish a VM full run that died after its last checkpoint, then publish it like vm_run.sh.
#
# scripts/resume_from_checkpoint.py runs main.py's own post-checkpoint tail (the network
# enrichers, scoring, every post-score step) and the board write; this wrapper gives it exactly
# vm_run.sh's environment (vm_lib.sh: .secrets/ + run config; main.py's load_dotenv() adds .env,
# e.g. ACPASS), a disk preflight, a live dual-signal memory watchdog that kills the job before
# the kernel OOM killer would (deploy/oracle/mem_watchdog.py), and vm_run.sh's publish step.
#
# Run DETACHED so an SSH drop cannot kill it:
#   setsid nohup bash deploy/oracle/vm_resume.sh --run >/dev/null 2>&1 < /dev/null &
# Modes (passed through): --run (default) | --enrich-only | --publish-only
# Logs: logs/vm-resume-<stamp>.log (run) and logs/vm-resume-<stamp>.mem.log (watchdog).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"

MODE="${1:---run}"
mkdir -p "$ROOT/logs"
STAMP="$(date +%Y%m%dT%H%M%S)"
LOG="$ROOT/logs/vm-resume-$STAMP.log"
MEMLOG="$ROOT/logs/vm-resume-$STAMP.mem.log"

. "$ROOT/deploy/oracle/vm_lib.sh"
vm_load_env "$LOG"

echo "==> VM resume $STAMP  mode=$MODE  role=$FORECLOSURE_ROLE  log=$LOG  mem=$MEMLOG" | tee -a "$LOG"
if pgrep -f -- "-m foreclosure_scraper|resume_from_checkpoint\.py" >/dev/null 2>&1; then
  echo "==> another board run is active — not starting" | tee -a "$LOG"; exit 75
fi

# Disk: the write keeps the old board until the renames, so it needs room for the new
# listings.json (~3.1 GB at 270K rows) + sidecar + slim + parts + shards (~1.5 GB), the
# timestamped backup of the old board (~2.8 GB) and a pre_publish checkpoint (~0.3 GB).
NEED_MB="${RESUME_MIN_FREE_MB:-9000}"
FREE_MB=$(df -Pm "$ROOT" | awk 'NR==2{print $4}')
if [[ "$FREE_MB" -lt "$NEED_MB" ]]; then
  echo "==> only ${FREE_MB} MB free, need ${NEED_MB} MB — not starting" | tee -a "$LOG"; exit 1
fi

uv sync --frozen >>"$LOG" 2>&1 || uv sync >>"$LOG" 2>&1
# Same as vm_run.sh: code + the Mac's latest hand-off files (the SOS ledger the resume applies).
git pull --rebase --autostash origin main >>"$LOG" 2>&1 || true
echo "==> code at $(git rev-parse --short HEAD)" | tee -a "$LOG"

START=$(date +%s)
uv run python scripts/resume_from_checkpoint.py "$MODE" >>"$LOG" 2>&1 &
PID=$!
python3 "$ROOT/deploy/oracle/mem_watchdog.py" --pid "$PID" --log "$MEMLOG" \
  --kill-total-mb "${RESUME_KILL_TOTAL_MB:-25600}" \
  --kill-avail-mb "${RESUME_KILL_AVAIL_MB:-700}" \
  --kill-swapfree-mb "${RESUME_KILL_SWAPFREE_MB:-400}" &
WD=$!
wait "$PID"
RC=$?
wait "$WD" 2>/dev/null
echo "==> exit=$RC  elapsed=$(( ($(date +%s)-START)/60 ))m  $(date)" | tee -a "$LOG"
tail -1 "$MEMLOG" | tee -a "$LOG"
grep -q "^KILLED" "$MEMLOG" && { echo "==> ⚠️  stopped by the memory watchdog" | tee -a "$LOG"; RC=137; }

if grep -q "count_drop_alert" "$LOG"; then
  echo "==> ⚠️  COUNT-DROP ALERT — see log." | tee -a "$LOG"; RC=2
fi
TOTAL=$(grep '"event": "web_artifact.written"' "$LOG" | grep -oE '"listings": [0-9]+' | tail -1 | grep -oE '[0-9]+' || echo "")
[[ -n "$TOTAL" ]] && echo "==> total listings this run: $TOTAL" | tee -a "$LOG"

if [[ "$RC" -eq 0 && "$MODE" != "--enrich-only" && -n "$TOTAL" ]]; then
  VM_PUBLISH_VERIFY=1 vm_publish_board "$LOG" \
    "vm run: refresh dashboard data ($(date +%Y-%m-%d), resumed from the run's checkpoint)"
  PRC=$?
  [[ "$PRC" -ne 0 ]] && RC=4
else
  echo "==> skipping publish (RC=$RC mode=$MODE)" | tee -a "$LOG"
fi
exit $RC
