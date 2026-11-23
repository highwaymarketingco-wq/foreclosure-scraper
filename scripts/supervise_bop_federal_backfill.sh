#!/usr/bin/env bash
# Self-healing supervisor for the federal BOP inmate-locator backfill (2026-11-23), same
# pattern as scripts/supervise_incarceration_backfill.sh. scripts/backfill_bop_federal.py
# is a SINGLE chunk per invocation (--max-queries 20000, long at the real 1 req/sec
# politeness pace to bop.gov) that exits when done -- nothing relaunches it on its own.
#
# FOUND DORMANT 2026-11-23: the script itself is a real, completed fix from 2026-10-23
# (scoped single-signal rewrite, same OOM-avoidance shape as backfill_incarceration.py),
# but nothing has ever scheduled it to actually run -- confirmed live via a bounded
# --dry-run: the underlying lookup still works cleanly (failed=0, blocked=0, real BOP.gov
# answers with names/timestamps), with 203,082 real NC/SC candidates sitting unaddressed.
# Unlike incarceration, this signal is NOT state-split (one combined NC/SC pool) --
# ONE process, not two.
#
# Once the eligible backlog hits 0, each relaunch is a quick no-op (enrich_bop_federal
# finds nothing to do and returns immediately) -- cheap enough to leave running rather
# than add logic to detect "done" and stop.
set -u
ROOT=/Users/cashhigh/foreclosure-scraper
cd "$ROOT" || exit 1
PY="$ROOT/.venv/bin/python3"
LOG="$ROOT/logs/bop_federal_supervisor.log"
mkdir -p "$ROOT/logs"

alive() {
  local n
  n=$(ps -eo command | grep -F "backfill_bop_federal.py" | grep -v grep | wc -l | tr -d ' ')
  [ "${n:-0}" -gt 0 ]
}

relaunch() {
  echo "$(date -u +%FT%TZ) relaunching bop_federal backfill" >> "$LOG"
  nohup "$PY" "$ROOT/scripts/backfill_bop_federal.py" --max-queries 20000 --allow-large \
    >> "$ROOT/logs/bop_federal_backfill_continuous.log" 2>&1 &
  disown
}

if ! alive; then
  relaunch
fi
