#!/usr/bin/env bash
# Daily incremental court-detail pass — drills NC eCourts (Tyler) + SC Public
# Index per-case pages for judgment / sale documents / sale_status (the
# confirmed-sold flag filters already-sold properties). Browser-based + capped;
# incremental so coverage of the ~3,900 cases builds across days.
set -uo pipefail
# launchd and Finder-launched applets start with a minimal PATH that lacks ~/.local/bin;
# dailycourt failed 31 days in a row on "uv: command not found" (audit O10/O12).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH ($PATH)" >&2; exit 127; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"; mkdir -p logs
LOG="$ROOT/logs/court-$(date +%Y%m%dT%H%M%S).log"

LOCK="$ROOT/logs/.court.lock"
if [[ -f "$LOCK" ]] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "==> another court pass (PID $(cat "$LOCK")) active; exit" | tee -a "$LOG"; exit 0; fi
echo $$ > "$LOCK"; trap 'rm -f "$LOCK"' EXIT

export NC_ECOURTS_INCREMENTAL=1 NC_ECOURTS_AUTH_CAP="${NC_ECOURTS_AUTH_CAP:-150}"
export SC_COURT_INCREMENTAL=1 SC_COURT_CAP="${SC_COURT_CAP:-80}"
# DEFAULT OFF (2026-09-21). The owner's current rule: robots.txt Disallow is not a wall,
# but a CAPTCHA, a login, a Cloudflare challenge and click-through terms still are (see
# CLAUDE.md "Hard constraints"). The WAF solver defeats a bot-check, so it is opt-in only.
export TYLER_USE_WAF_SOLVER="${TYLER_USE_WAF_SOLVER:-0}"
export COURT_MAX_SECONDS="${COURT_MAX_SECONDS:-3600}"
export PYTHONUNBUFFERED=1
echo "==> daily court detail $(date)" | tee -a "$LOG"
uv run python -m playwright install chromium >>"$LOG" 2>&1 || true
uv run scrapling install >>"$LOG" 2>&1 || true
uv run python scripts/patch_court_detail.py >>"$LOG" 2>&1
echo "==> exit=$? $(date)" | tee -a "$LOG"
ls -1t "$ROOT"/logs/court-*.log 2>/dev/null | tail -n +10 | xargs rm -f 2>/dev/null || true
