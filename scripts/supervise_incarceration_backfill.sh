#!/usr/bin/env bash
# Self-healing supervisor for the incarceration backfill catch-up (2026-11-12), same
# pattern as the VM's scripts/supervise_wrappers.sh. scripts/backfill_incarceration.py
# is a SINGLE chunk per invocation (--max-queries 20000, ~5.6h at the real 1 req/sec
# politeness pace) that exits when done -- nothing relaunches it on its own. Real
# backlog measured live 2026-11-12: 119,605 eligible NC/SC names (down from 203,233 on
# 2026-10-23, so whatever ran before this really did work -- it just stopped getting
# relaunched). This script notices it died and starts the next chunk, cron-driven every
# 5 minutes, so it runs until the backlog is actually gone instead of sitting idle again.
#
# RUNS TWO, STATE-SCOPED (2026-11-12, same day, after the first version ran one unscoped
# process for ~80 min): --state NC and --state SC are two SEPARATE processes instead of
# one process alternating between both. Safe to run concurrently because NC and SC hit
# TWO DIFFERENT lookup hosts (webapps6.doc.state.nc.us vs SC's SCDC site) and
# enrich_incarceration()'s 1 req/sec pacing is per-process -- so this doubles real
# throughput (two independent 1 req/sec streams) rather than hammering one host twice as
# fast. Each is tracked and relaunched independently so one finishing/dying never waits
# on or blocks the other.
#
# Once a state's eligible backlog hits 0, each relaunch is a quick no-op (enrich_
# incarceration finds nothing to do and returns immediately) -- cheap enough to leave
# running rather than add logic to detect "done" and stop.
set -u
ROOT=/Users/cashhigh/foreclosure-scraper
cd "$ROOT" || exit 1
PY="$ROOT/.venv/bin/python3"
LOG="$ROOT/logs/incarceration_supervisor.log"
mkdir -p "$ROOT/logs"

alive() {  # alive "<state>" -> exit 0 if that state's process is running
  local n
  n=$(ps -eo command | grep -F "backfill_incarceration.py" | grep -F -- "--state $1" | grep -v grep | wc -l | tr -d ' ')
  [ "${n:-0}" -gt 0 ]
}

relaunch() {  # relaunch "<state>"
  echo "$(date -u +%FT%TZ) relaunching incarceration backfill ($1)" >> "$LOG"
  nohup "$PY" "$ROOT/scripts/backfill_incarceration.py" --state "$1" --max-queries 20000 --allow-large \
    >> "$ROOT/logs/incarceration_backfill_${1}_continuous.log" 2>&1 &
  disown
}

for st in NC SC; do
  if ! alive "$st"; then
    relaunch "$st"
  fi
done
