#!/usr/bin/env bash
# Self-healing supervisor for the comps-accuracy verifier (2026-11-23), same pattern as
# supervise_bop_federal_backfill.sh / supervise_incarceration_backfill.sh.
#
# FOUND DORMANT 2026-11-23: src/foreclosure_scraper/verification/verifiers/comps_buncombe.py
# is a real, sophisticated, working verifier (checks board comps against Buncombe county's
# own ArcGIS deed record, 93.7% accuracy validated 2026-10-03) auto-discovered by the
# verification framework's pkgutil scan (SIGNAL="comps", no manual wiring needed) -- but
# nothing has ever scheduled it. Confirmed live: 9,615 Buncombe comps rows apply, 9,376
# never verified at all (due_new). A real 15-row test batch confirmed clean (15/15
# confirmed, 0 errors, ledger updated, git pushed) before this was added.
#
# verification_sweep.py is ledger-only (writes docs/handoff/verification/comps, never
# touches board_lock or docs/listings*) -- safe to run alongside every other lane. Bounded
# at --max-rows 300/invocation (~27min at the ~5.4s/row observed pace) so a relaunch after
# a kill never loses much in-flight state; once the initial backlog clears, each invocation
# naturally finds little to do (30-day TTL) and exits fast.
set -u
ROOT=/Users/cashhigh/foreclosure-scraper
cd "$ROOT" || exit 1
PY="$ROOT/.venv/bin/python3"
LOG="$ROOT/logs/comps_verify_supervisor.log"
mkdir -p "$ROOT/logs"

alive() {
  local n
  n=$(ps -eo command | grep -F "verification_sweep.py --signal comps" | grep -v grep | wc -l | tr -d ' ')
  [ "${n:-0}" -gt 0 ]
}

relaunch() {
  echo "$(date -u +%FT%TZ) relaunching comps verify sweep" >> "$LOG"
  nohup "$PY" "$ROOT/scripts/verification_sweep.py" --signal comps --max-rows 300 \
    >> "$ROOT/logs/comps_verify_continuous.log" 2>&1 &
  disown
}

if ! alive; then
  relaunch
fi
