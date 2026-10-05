#!/usr/bin/env bash
# The VM side of the cloud split — the datacenter host's run.
#
# Linux analog of scripts/run_local.sh, minus the macOS bits (no caffeinate /
# launchd). It runs only the datacenter-safe sources (FORECLOSURE_ROLE=vm),
# ingests the Mac's stealth hand-off (national.stealth_handoff), does ALL the
# RAM-heavy enrichment, and publishes the board to GitHub Pages.
#
# Run manually:   bash deploy/oracle/vm_run.sh
# Scheduled:      systemd timer (deploy/oracle/install_timer.sh)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"

mkdir -p "$ROOT/logs" "$ROOT/docs/handoff"
STAMP="$(date +%Y%m%dT%H%M%S)"
LOG="$ROOT/logs/vm-run-$STAMP.log"

# Secrets + run config (FORECLOSURE_ROLE=vm, assessor-card, prior-merge override, ...) live in
# vm_lib.sh, shared with vm_resume.sh so a resumed run gets exactly the same environment.
. "$ROOT/deploy/oracle/vm_lib.sh"
vm_load_env "$LOG"

echo "==> VM run $STAMP  role=vm  vision=$VISION_PROVIDER  log=$LOG" | tee -a "$LOG"
uv sync --frozen >>"$LOG" 2>&1 || uv sync >>"$LOG" 2>&1

# Pull the Mac's stealth hand-off (+ any board changes) before running.
git pull --rebase --autostash origin main >>"$LOG" 2>&1 || true

START=$(date +%s)
uv run python -m foreclosure_scraper >>"$LOG" 2>&1
RC=$?
echo "==> exit=$RC  elapsed=$(( ($(date +%s)-START)/60 ))m  $(date)" | tee -a "$LOG"

# Fail-loud signals surfaced at the tail (mirror run_local.sh).
if grep -q "count_drop_alert" "$LOG"; then
  echo "==> ⚠️  COUNT-DROP ALERT — a source may be broken. See log." | tee -a "$LOG"; RC=2
fi
TOTAL=$(grep '"event": "web_artifact.written"' "$LOG" | grep -oE '"listings": [0-9]+' | tail -1 | grep -oE '[0-9]+' || echo "")
[[ -n "$TOTAL" ]] && echo "==> total listings this run: $TOTAL" | tee -a "$LOG"

# ---- publish board to GitHub Pages on a healthy run ------------------------
if [[ "$RC" -eq 0 && -f "$ROOT/docs/listings.json" ]]; then
  vm_publish_board "$LOG" "vm run: refresh dashboard data ($(date +%Y-%m-%d))" || true
else
  echo "==> skipping publish (RC=$RC)" | tee -a "$LOG"
fi

ls -1t "$ROOT"/logs/vm-run-*.log 2>/dev/null | tail -n +13 | xargs rm -f 2>/dev/null || true
exit $RC
