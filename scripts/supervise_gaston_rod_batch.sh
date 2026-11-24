#!/usr/bin/env bash
# Self-healing driver for fill_gaston_rod_batch.py (2026-11-24). ~24,500 Gaston
# rows need the ROD lien-existence check; each run processes a small, safe
# batch (--max-lookups 20, confirmed live to stay under Gaston's own ~27-29
# request rate limit) and exits -- this just makes sure a fresh batch starts
# every cron tick as long as the previous one has finished. Designed to be
# cron'd every 10 minutes (a single run takes ~5 min including the Cloudflare
# solve + patch); the `alive` check is the same ps|grep|grep -v grep pattern
# used by every other supervisor this session (pgrep -f matches its own
# invocation and must never be used here).
set -u
ROOT="${FORECLOSURE_ROOT:-$HOME/foreclosure-scraper}"
cd "$ROOT" || exit 1
PY="$ROOT/.venv/bin/python3"
LOG="$ROOT/logs/gaston_rod_batch_continuous.log"
mkdir -p "$ROOT/logs"

alive() {
  local n
  n=$(ps -eo command | grep -F "fill_gaston_rod_batch.py" | grep -v grep | wc -l | tr -d ' ')
  [ "${n:-0}" -gt 0 ]
}

if alive; then
  exit 0
fi

echo "$(date -u +%FT%TZ) starting gaston_rod_batch" >> "$LOG"
nohup "$PY" scripts/fill_gaston_rod_batch.py --max-lookups 20 >> "$LOG" 2>&1 &
disown
