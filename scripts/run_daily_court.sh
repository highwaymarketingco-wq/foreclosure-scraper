#!/usr/bin/env bash
# Daily incremental court-detail pass — drills NC eCourts (Tyler) + SC Public
# Index per-case pages for judgment / sale documents / sale_status (the
# confirmed-sold flag filters already-sold properties). Browser-based + capped;
# incremental so coverage of the ~3,900 cases builds across days.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"; mkdir -p logs
LOG="$ROOT/logs/court-$(date +%Y%m%dT%H%M%S).log"

LOCK="$ROOT/logs/.court.lock"
if [[ -f "$LOCK" ]] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "==> another court pass (PID $(cat "$LOCK")) active; exit" | tee -a "$LOG"; exit 0; fi
echo $$ > "$LOCK"; trap 'rm -f "$LOCK"' EXIT

export NC_ECOURTS_INCREMENTAL=1 NC_ECOURTS_AUTH_CAP="${NC_ECOURTS_AUTH_CAP:-150}"
export SC_COURT_INCREMENTAL=1 SC_COURT_CAP="${SC_COURT_CAP:-80}"
export TYLER_USE_WAF_SOLVER="${TYLER_USE_WAF_SOLVER:-1}"
export COURT_MAX_SECONDS="${COURT_MAX_SECONDS:-3600}"
export PYTHONUNBUFFERED=1
echo "==> daily court detail $(date)" | tee -a "$LOG"
uv run python -m playwright install chromium >>"$LOG" 2>&1 || true
uv run scrapling install >>"$LOG" 2>&1 || true
uv run python scripts/patch_court_detail.py >>"$LOG" 2>&1
echo "==> exit=$? $(date)" | tee -a "$LOG"
ls -1t "$ROOT"/logs/court-*.log 2>/dev/null | tail -n +10 | xargs rm -f 2>/dev/null || true
