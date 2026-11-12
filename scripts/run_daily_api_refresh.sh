#!/usr/bin/env bash
# Daily refresh of the browserless (JSON/API) sources — keeps churning REO
# (Fannie HomePath, foreclosure.com, HUD, VA REO, CourtListener, …) current so
# day-old "sold/removed" listings don't 404. Fast: no stealth browser.
set -uo pipefail
# launchd and Finder-launched applets start with a minimal PATH that lacks ~/.local/bin;
# dailycourt failed 31 days in a row on "uv: command not found" (audit O10/O12).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
command -v uv >/dev/null 2>&1 || { echo "uv not found on PATH ($PATH)" >&2; exit 127; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"; SECRETS="$ROOT/.secrets"; mkdir -p logs
# daily_api_refresh.py writes the board, and write_artifact now refuses without the board
# lock (audit O3). Re-exec ONCE under it; the second pass sees the lock and carries on.
if [ -z "${FORECLOSURE_BOARD_LOCK_HELD:-}" ]; then
  exec "$ROOT/scripts/with_board_lock.sh" run_daily_api_refresh --max-runtime 10800 -- bash "$ROOT/scripts/run_daily_api_refresh.sh" "$@"
fi
LOG="$ROOT/logs/api-refresh-$(date +%Y%m%dT%H%M%S).log"

LOCK="$ROOT/logs/.api-refresh.lock"
if [[ -f "$LOCK" ]] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "==> another api-refresh (PID $(cat "$LOCK")) active; exit" | tee -a "$LOG"; exit 0; fi
echo $$ > "$LOCK"; trap 'rm -f "$LOCK"' EXIT

load() { [[ -f "$2" ]] && export "$1"="$(cat "$2")"; }
load GITHUB_MODELS_TOKEN "$SECRETS/github_models_token.txt"  # not used, harmless
export PYTHONUNBUFFERED=1
echo "==> daily api refresh $(date)" | tee -a "$LOG"
uv run python scripts/daily_api_refresh.py >>"$LOG" 2>&1
echo "==> exit=$? $(date)" | tee -a "$LOG"
ls -1t "$ROOT"/logs/api-refresh-*.log 2>/dev/null | tail -n +10 | xargs rm -f 2>/dev/null || true
