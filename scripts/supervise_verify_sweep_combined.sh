#!/usr/bin/env bash
# Self-healing supervisor for 13 previously-unscheduled verification_sweep.py signals
# (2026-11-23), same pattern as supervise_comps_verify.sh.
#
# FOUND DORMANT 2026-11-23: a systematic survey of src/foreclosure_scraper/verification/
# verifiers/ found only comps (Mac) and tax_lien (VM) were actually scheduled anywhere.
# These 13 signals -- bankruptcy_stay, code_enforcement, vacant_structure, court_wall,
# divorce, elderly_disabled, foreclosure_rod, foreclosure_sale_list, heir_roll,
# jail_booking, lien_registry_wall, nc_ecourts_case, probate_heir -- have real, working
# verifier code and a combined ~275,000 never-checked (due_new) rows, but nothing ever
# ran them. Confirmed clean with a real 10-row/signal test (zero errors across 17 real
# external sources, git pushed 58d2a14) before adding standing scheduling.
#
# court_wall/divorce/lien_registry_wall are WALL-CONFIRMATION verifiers (expected to
# return mostly "wall" verdicts -- they keep the gap_matrix walled-bucket classification
# fresh, not generate new leads) -- included anyway, that's real, correct, valuable work
# (the "stale_scope" staleness problem gap_matrix flagged earlier). The other 10 generate
# real confirmed/refuted lead verdicts.
#
# verification_sweep.py's --signal flag takes multiple values in ONE invocation with a
# PER-SIGNAL --max-rows cap -- one combined process covers all 13, no need for 13 separate
# supervisors. Ledger-only (docs/handoff/verification/<signal>), never touches board_lock
# or docs/listings* -- safe alongside every other lane.
set -u
ROOT=/Users/cashhigh/foreclosure-scraper
cd "$ROOT" || exit 1
PY="$ROOT/.venv/bin/python3"
LOG="$ROOT/logs/verify_sweep_combined_supervisor.log"
mkdir -p "$ROOT/logs"

SIGNALS=(
  --signal bankruptcy_stay --signal code_enforcement --signal vacant_structure
  --signal court_wall --signal divorce --signal elderly_disabled
  --signal foreclosure_rod --signal foreclosure_sale_list --signal heir_roll
  --signal jail_booking --signal lien_registry_wall --signal nc_ecourts_case
  --signal probate_heir
)

alive() {
  local n
  n=$(ps -eo command | grep -F "verification_sweep.py" | grep -F "bankruptcy_stay" | grep -v grep | wc -l | tr -d ' ')
  [ "${n:-0}" -gt 0 ]
}

relaunch() {
  echo "$(date -u +%FT%TZ) relaunching combined verify sweep (13 signals)" >> "$LOG"
  nohup "$PY" "$ROOT/scripts/verification_sweep.py" "${SIGNALS[@]}" --max-rows 50 \
    >> "$ROOT/logs/verify_sweep_combined_continuous.log" 2>&1 &
  disown
}

if ! alive; then
  relaunch
fi
