#!/usr/bin/env bash
# Self-healing supervisor for the standing self-looping board wrappers (2026-11-11).
#
# WHY THIS EXISTS. Every wrapper below is its own `for i in $(seq 1 N); do CMD;
# sleep S; done` loop -- by design, bounded, so it exhausts on its own after N
# cycles rather than accumulating forever. That means something has to notice
# when a wrapper's bound runs out and relaunch it. Tonight that "something" was
# a human (Claude) manually re-checking `ps` every so often across a long
# session -- real, but it leaves multi-hour gaps whenever nobody is watching
# (confirmed live 2026-11-11: comps_sweep/deed_chain_v2 died in an earlier VM
# crash and sat dead for a while; separately meck_gis_attrs/meck_code_
# enforcement/meck_tax/tax_lien all exhausted their bounds during one
# unattended multi-hour gap and nobody relaunched them until the next manual
# check). This script is that "something", meant to run from cron every few
# minutes so a wrapper is never down for longer than one cron tick.
#
# LIVENESS CHECK: `ps -eo cmd | grep PATTERN | grep -v grep | wc -l`, NOT
# `pgrep -f PATTERN`. Confirmed live on this host: `pgrep -f` matches ITS OWN
# invocation even for a pattern that cannot possibly be real (tested with a
# nonsense string -- pgrep returned its own PID, exit 0). That would make a
# supervisor built on pgrep -f ALWAYS report "running" and never relaunch
# anything -- the exact opposite of this script's job. The `ps | grep | grep
# -v grep` pattern this session already used successfully many times tonight
# does not have that failure mode (the grep processes' own cmdlines contain
# the literal word "grep", which the final `grep -v grep` strips before the
# count, so counting survivors correctly answers "is the REAL target alive").
#
# Each relaunch uses the exact same self-looping form already proven safe
# tonight: no `|| break` anywhere (see feedback_selflooping_wrapper_or_break_
# fragility_2026-11-11 -- a single BoardLockBusy must not kill the loop), and
# every path is absolute so a cron environment's bare PATH can't break it.
set -u
ROOT=/home/opc/foreclosure-scraper
cd "$ROOT" || exit 1
PY="$ROOT/.venv/bin/python3.12"
LOG="$ROOT/logs/supervisor.log"
mkdir -p "$ROOT/logs"

alive() {  # alive "<match-pattern>" -> exit 0 if a real process matches, 1 if not
  local n
  n=$(ps -eo cmd | grep -F "$1" | grep -v grep | wc -l | tr -d ' ')
  [ "${n:-0}" -gt 0 ]
}

relaunch() {  # relaunch "<name>" "<shell command to launch, already self-looping>"
  echo "$(date -u +%FT%TZ) relaunching $1" >> "$LOG"
  nohup setsid bash -c "$2" < /dev/null > /dev/null 2>&1 &
  disown
}

if ! alive "backfill_gis_attrs_boardwide.py"; then
  relaunch gis_attrs_boardwide \
    "cd '$ROOT' && for i in \$(seq 1 150); do $PY scripts/backfill_gis_attrs_boardwide.py --allow-large --max-rows 3000 >> logs/gis_attrs_backfill_continuous.log 2>&1; sleep 15; done"
fi

if ! alive "backfill_mecklenburg_gis_attrs.py"; then
  relaunch meck_gis_attrs \
    "cd '$ROOT' && for i in \$(seq 1 300); do BOARD_PATCH_ALLOW_LARGE=1 $PY scripts/backfill_mecklenburg_gis_attrs.py --allow-large --max-rows 3000 >> logs/backfill_meck_gis_attrs_continuous.log 2>&1; sleep 15; done"
fi

if ! alive "backfill_mecklenburg_code_enforcement.py"; then
  relaunch meck_code_enforcement \
    "cd '$ROOT' && for i in \$(seq 1 300); do BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 $PY scripts/backfill_mecklenburg_code_enforcement.py --batch-size 300 --max-batches 1 >> logs/backfill_meck_codeenf_continuous.log 2>&1; sleep 15; done"
fi

if ! alive "backfill_mecklenburg_tax.py"; then
  relaunch meck_tax \
    "cd '$ROOT' && for i in \$(seq 1 300); do BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 $PY scripts/backfill_mecklenburg_tax.py --rounds 3 >> logs/backfill_meck_tax_continuous.log 2>&1; sleep 15; done"
fi

if ! alive "run_comps_sweep.sh"; then
  relaunch comps_sweep "bash '$ROOT/scripts/run_comps_sweep.sh'"
fi

if ! alive "backfill_deed_chain_v2.py"; then
  relaunch deed_chain_v2 \
    "cd '$ROOT' && for i in \$(seq 1 20); do $PY scripts/backfill_deed_chain_v2.py --allow-large >> logs/manual_deed_chain_v2_run.log 2>&1; sleep 20; done"
fi

if ! alive "verification_sweep.py --signal tax_lien"; then
  relaunch tax_lien \
    "cd '$ROOT' && HANDOFF_PUSH=0 $PY scripts/verification_sweep.py --signal tax_lien >> logs/manual_tax_lien_relaunch.log 2>&1"
fi
