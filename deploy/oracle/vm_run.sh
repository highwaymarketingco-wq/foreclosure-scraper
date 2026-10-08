#!/usr/bin/env bash
# The VM side of the cloud split — the datacenter host's full run.
#
# Linux analog of scripts/run_local.sh, minus the macOS bits (no caffeinate /
# launchd). It runs only the datacenter-safe sources (FORECLOSURE_ROLE=vm),
# ingests the Mac's stealth hand-off (national.stealth_handoff), does ALL the
# RAM-heavy enrichment, and publishes the board to GitHub Pages.
#
# Usage (run DETACHED so an SSH drop cannot kill it):
#   setsid nohup bash deploy/oracle/vm_run.sh [--stop-before-publish] >/dev/null 2>&1 < /dev/null &
#   Scheduled: systemd timer (deploy/oracle/install_timer.sh; publishes, see there)
#
# --stop-before-publish (or FULLRUN_STOP_BEFORE_PUBLISH=1): run everything, save the scored board
#     as the pre_publish checkpoint (data/checkpoint/), and stop: no board files written to docs/,
#     no commit, no push. Publish it after review with vm_resume.sh --publish-only. The gated
#     launch, step by step: docs/HANDOFF.md item 72.
# RUN_PIN_COMMIT=<sha>: run exactly that commit (fast-forward to it) or refuse; never pulls newer.
#     Check the pin out before starting, so the script itself is the pinned one:
#       git fetch origin && git merge --ff-only --autostash <sha>
#     (if the checkout changes this script anyway, it re-runs the checked-out copy once).
# Before the run (each refusal exits 1, nothing started): another board job running (75); a
#     pre_publish checkpoint waiting to be published (RUN_DISCARD_PENDING_PUBLISH=1 overwrites
#     it); free disk under the full run's need (vm_lib.sh: VM_PUBLISH_BASE_MB + the current
#     board's size + VM_RUN_GROWTH_MB, ~11.4 GB today; RUN_MIN_FREE_MB overrides); reference data
#     missing or damaged (deploy/oracle/refdata_check.py). No active swap is a loud warning.
# During: deploy/oracle/mem_watchdog.py stops the run before the kernel OOM killer would
#     (RUN_KILL_TOTAL_MB / RUN_KILL_AVAIL_MB / RUN_KILL_SWAPFREE_MB, defaults 25600 / 700 / 400).
# Logs: logs/vm-run-<stamp>.log (run) and logs/vm-run-<stamp>.mem.log (watchdog).
# Exit: python's code (0 ok, 3 write/checkpoint failed, 6 stale tiers, 75 lock busy), 1 refused,
#     2 count-drop alert, 70 watchdog could not run, 137 stopped by the watchdog.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"

STOP=0
for a in "$@"; do
  case "$a" in
    --stop-before-publish) STOP=1 ;;
    -h|--help) sed -n '2,/^set -uo/p' "$0" | sed '$d'; exit 0 ;;
    *) echo "vm_run.sh: unknown argument: $a (see --help)" >&2; exit 64 ;;
  esac
done
case "$(printf '%s' "${FULLRUN_STOP_BEFORE_PUBLISH:-}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on) STOP=1 ;;
esac

mkdir -p "$ROOT/logs" "$ROOT/docs/handoff"
STAMP="${VM_RUN_STAMP:-$(date +%Y%m%dT%H%M%S)}"
LOG="$ROOT/logs/vm-run-$STAMP.log"
MEMLOG="$ROOT/logs/vm-run-$STAMP.mem.log"

# Secrets + run config (FORECLOSURE_ROLE=vm, assessor-card, prior-merge override, ...) and the
# run-safety helpers live in vm_lib.sh, shared with vm_resume.sh.
. "$ROOT/deploy/oracle/vm_lib.sh"
vm_load_env "$LOG"

echo "==> VM run $STAMP  role=vm  vision=$VISION_PROVIDER  stop_before_publish=$STOP  log=$LOG  mem=$MEMLOG" | tee -a "$LOG"
if vm_board_job_active; then
  echo "==> another board run is active — not starting" | tee -a "$LOG"; exit 75
fi

# ---- the code to run: first, so every check below is the checked-out code's own ---------------
_self_sum() { cat "$ROOT/deploy/oracle/vm_run.sh" "$ROOT/deploy/oracle/vm_lib.sh" 2>/dev/null | cksum; }
SELF_SUM="$(_self_sum)"
PIN="${RUN_PIN_COMMIT:-}"
vm_checkout "$LOG" "$PIN" || exit 1
if [[ "$(_self_sum)" != "$SELF_SUM" && "${VM_RUN_REEXEC:-0}" != "1" ]]; then
  echo "==> vm_run.sh / vm_lib.sh changed with the checkout: re-running the checked-out copy" | tee -a "$LOG"
  VM_RUN_REEXEC=1 VM_RUN_STAMP="$STAMP" exec bash "$ROOT/deploy/oracle/vm_run.sh" "$@"
fi
vm_handoff_note "$LOG"

# ---- preflights ----------------------------------------------------------------------------------
CKPT_DIR="${FORECLOSURE_CHECKPOINT_DIR:-data/checkpoint}"
PENDING=$(python3 -c 'import json,sys
try: m = json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
if m.get("phase") == "pre_publish": print(m.get("count"), "rows saved", m.get("saved_at"))' \
  "$CKPT_DIR/manifest.json" 2>/dev/null)
if [[ -n "$PENDING" ]]; then
  if [[ "${RUN_DISCARD_PENDING_PUBLISH:-0}" == "1" ]]; then
    echo "==> ⚠️  discarding the unpublished pre_publish checkpoint ($PENDING): this run replaces it" | tee -a "$LOG"
  else
    echo "==> a scored board is waiting to be published: pre_publish checkpoint in $CKPT_DIR ($PENDING)." \
         "This run would overwrite it. Publish it (vm_resume.sh --publish-only) or set" \
         "RUN_DISCARD_PENDING_PUBLISH=1 — not starting" | tee -a "$LOG"
    exit 1
  fi
fi
WHY="full run: publish ${VM_PUBLISH_BASE_MB} + replaced board $(vm_board_bytes_mb) + in-run ${VM_RUN_GROWTH_MB} = $(vm_full_run_need_mb); vm_lib.sh"
NEED_MB="${RUN_MIN_FREE_MB:-$(vm_full_run_need_mb)}"
[[ -n "${RUN_MIN_FREE_MB:-}" ]] && WHY="RUN_MIN_FREE_MB override; computed $WHY"
vm_preflight_disk "$LOG" "$NEED_MB" "$WHY" || exit 1
vm_preflight_swap "$LOG"
vm_preflight_refdata "$LOG" || { echo "==> reference data not ready — not starting" | tee -a "$LOG"; exit 1; }

uv sync --frozen >>"$LOG" 2>&1 || uv sync >>"$LOG" 2>&1

if [[ "$STOP" == "1" ]]; then export FULLRUN_STOP_BEFORE_PUBLISH=1; else unset FULLRUN_STOP_BEFORE_PUBLISH; fi
START=$(date +%s)
vm_run_watched "$LOG" "$MEMLOG" RUN uv run python -m foreclosure_scraper
RC=$VM_RC
echo "==> exit=$RC  elapsed=$(( ($(date +%s)-START)/60 ))m  $(date)" | tee -a "$LOG"

vm_report_swallowed "$LOG"
# Fail-loud signals surfaced at the tail (mirror run_local.sh).
if grep -q "count_drop_alert" "$LOG"; then
  echo "==> ⚠️  COUNT-DROP ALERT — a source may be broken. See log." | tee -a "$LOG"; RC=2
fi

if [[ "$STOP" == "1" ]]; then
  # ---- gated launch: the scored board waits in data/checkpoint/ for review -----------------------
  SAVED=$(grep '"orchestrator.stopped_before_publish"' "$LOG" | grep -oE '"leads": [0-9]+' | tail -1 | grep -oE '[0-9]+' || true)
  if [[ -n "$SAVED" ]]; then
    PNEED=$(vm_publish_need_mb); FREE=$(vm_free_mb)
    {
      echo "==> STOPPED BEFORE PUBLISH: $SAVED scored rows saved as the pre_publish checkpoint ($CKPT_DIR)."
      echo "==> Nothing was written to the board files in docs/, nothing committed or pushed."
      echo "==> Review:   uv run python scripts/resume_from_checkpoint.py"
      echo "==>           uv run python scripts/board_selfcheck.py --checkpoint"
      echo "==> Publish:  RESUME_PIN_COMMIT=$(git rev-parse HEAD) setsid nohup bash deploy/oracle/vm_resume.sh --publish-only >/dev/null 2>&1 < /dev/null &"
      echo "==> disk now ${FREE} MB free; the publish needs ${PNEED} MB"
    } | tee -a "$LOG"
    [[ "${FREE:-0}" -lt "$PNEED" ]] && echo "==> ⚠️  not enough disk to publish yet: vm_resume.sh will refuse until ${PNEED} MB are free" | tee -a "$LOG"
  else
    echo "==> ⚠️  no pre_publish checkpoint was saved (RC=$RC): nothing to review or publish" | tee -a "$LOG"
  fi
else
  TOTAL=$(grep '"event": "web_artifact.written"' "$LOG" | grep -oE '"listings": [0-9]+' | tail -1 | grep -oE '[0-9]+' || echo "")
  [[ -n "$TOTAL" ]] && echo "==> total listings this run: $TOTAL" | tee -a "$LOG"
  # ---- publish board to GitHub Pages on a healthy run ----------------------------------------------
  if [[ "$RC" -eq 0 && -f "$ROOT/docs/listings.json" ]]; then
    vm_publish_board "$LOG" "vm run: refresh dashboard data ($(date +%Y-%m-%d))" || true
  else
    echo "==> skipping publish (RC=$RC)" | tee -a "$LOG"
  fi
fi

ls -1t "$ROOT"/logs/vm-run-*.log 2>/dev/null | grep -v '\.mem\.log$' | tail -n +13 | xargs rm -f 2>/dev/null || true
ls -1t "$ROOT"/logs/vm-run-*.mem.log 2>/dev/null | tail -n +13 | xargs rm -f 2>/dev/null || true
exit $RC
