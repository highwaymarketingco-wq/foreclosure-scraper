#!/usr/bin/env bash
# Finish a VM full run that died after its last checkpoint, then publish it like vm_run.sh.
#
# scripts/resume_from_checkpoint.py runs main.py's own post-checkpoint tail (the network
# enrichers, scoring, every post-score step) and the board write; this wrapper gives it exactly
# vm_run.sh's environment (vm_lib.sh: .secrets/ + run config; main.py's load_dotenv() adds .env,
# e.g. ACPASS), a disk preflight, a live dual-signal memory watchdog that kills the job before
# the kernel OOM killer would (deploy/oracle/mem_watchdog.py), and vm_run.sh's publish step. The
# preflights, the pin and the watchdog are vm_lib.sh's, shared with vm_run.sh (2026-10-06).
# --publish-only also publishes the pre_publish checkpoint of a gated full run
# (vm_run.sh --stop-before-publish); docs/HANDOFF.md item 72.
#
# Run DETACHED so an SSH drop cannot kill it:
#   setsid nohup bash deploy/oracle/vm_resume.sh --run >/dev/null 2>&1 < /dev/null &
# Modes (passed through): --run (default) | --enrich-only | --publish-only
# RESUME_PIN_COMMIT=<sha>: run exactly that commit instead of pulling origin/main (see below).
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
if vm_board_job_active; then
  echo "==> another board run is active — not starting" | tee -a "$LOG"; exit 75
fi

# Disk: the write keeps the old board until the renames, so it needs room for the new board files
# beside the old ones, the timestamped backup of the old board and a pre_publish checkpoint:
# vm_lib.sh's publish need (VM_PUBLISH_BASE_MB + the current board's size; 9,432 MB with today's
# 223,832-row board, measured at 355K rows on this VM, cf372926). It was a flat 9,000, sized at 270K.
WHY="publish: ${VM_PUBLISH_BASE_MB} + replaced board $(vm_board_bytes_mb) = $(vm_publish_need_mb); vm_lib.sh"
NEED_MB="${RESUME_MIN_FREE_MB:-$(vm_publish_need_mb)}"
[[ -n "${RESUME_MIN_FREE_MB:-}" ]] && WHY="RESUME_MIN_FREE_MB override; computed $WHY"
vm_preflight_disk "$LOG" "$NEED_MB" "$WHY" || exit 1
vm_preflight_swap "$LOG"

# PINNED (2026-10-06): RESUME_PIN_COMMIT=<sha> runs exactly the reviewed commit or nothing. origin/main
# moves all day (other agents push), so pulling it would run whatever is newest. Check the pin out
# BEFORE starting this script, so the copy bash is executing is the pinned one:
#   git fetch origin && git merge --ff-only --autostash <sha>
# Unpinned: same as vm_run.sh: code + the Mac's latest hand-off files (the SOS ledger the resume applies).
PIN="${RESUME_PIN_COMMIT:-}"
vm_checkout "$LOG" "$PIN" || exit 1
uv sync --frozen >>"$LOG" 2>&1 || uv sync >>"$LOG" 2>&1

START=$(date +%s)
vm_run_watched "$LOG" "$MEMLOG" RESUME uv run python scripts/resume_from_checkpoint.py "$MODE"
RC=$VM_RC
echo "==> exit=$RC  elapsed=$(( ($(date +%s)-START)/60 ))m  $(date)" | tee -a "$LOG"

if grep -q "count_drop_alert" "$LOG"; then
  echo "==> ⚠️  COUNT-DROP ALERT — see log." | tee -a "$LOG"; RC=2
fi
TOTAL=$(grep '"event": "web_artifact.written"' "$LOG" | grep -oE '"listings": [0-9]+' | tail -1 | grep -oE '[0-9]+' || echo "")
[[ -n "$TOTAL" ]] && echo "==> total listings this run: $TOTAL" | tee -a "$LOG"

if [[ "$RC" -eq 0 && "$MODE" != "--enrich-only" && -n "$TOTAL" ]]; then
  HOW="resumed from the run's checkpoint"
  [[ "$MODE" == "--publish-only" ]] && HOW="published from the run's pre_publish checkpoint"
  VM_PUBLISH_VERIFY=1 vm_publish_board "$LOG" "vm run: refresh dashboard data ($(date +%Y-%m-%d), $HOW)"
  PRC=$?
  [[ "$PRC" -ne 0 ]] && RC=4
else
  echo "==> skipping publish (RC=$RC mode=$MODE)" | tee -a "$LOG"
fi
exit $RC
