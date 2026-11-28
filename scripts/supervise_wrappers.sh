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
#
# HEALTH CHECK ADDED 2026-11-18: "alive" only ever answered "is a process
# running", never "is it actually succeeding". Found live: a board resharding
# on 2026-11-16 left board.manifest.json stale (45 real parts on disk, 6
# recorded), so every wrapper that touches the board hit the SAME
# BoardIntegrityError on every single invocation -- exhaust its bound (a few
# thousand seconds), supervisor sees it as "exited", relaunches a fresh bound,
# repeat. ~10,000 identical failures over 2 days, completely invisible,
# because "alive" was true the entire time (something was always running,
# it just never once succeeded). check_stuck() below tails each wrapper's own
# log and counts recent known-error signatures; past a threshold it writes a
# single-line, timestamped, greppable alert to logs/SUPERVISOR_ALERTS.log
# instead of silently continuing. Deliberately alert-only, not a kill switch:
# this is about catching the NEXT one inside minutes instead of days, not
# about guessing when it's safe to stop a wrapper automatically.
set -u
ROOT=/home/opc/foreclosure-scraper
cd "$ROOT" || exit 1
PY="$ROOT/.venv/bin/python3.12"
LOG="$ROOT/logs/supervisor.log"
ALERTLOG="$ROOT/logs/SUPERVISOR_ALERTS.log"
mkdir -p "$ROOT/logs"
export BOARD_BACKUP_KEEP=1  # persist only 1 backup per type -- /etc/environment does NOT reach
                            # cron-spawned processes (confirmed 2026-11-27); this export is the
                            # only durable place for it, since relaunch()'s children inherit
                            # whatever this script's own environment holds at call time.

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

check_stuck() {  # check_stuck "<name>" "<log file>" -> appends an alert if the
                 # tail looks like a repeated-failure loop, never blocks/stops anything
  local name="$1" logfile="$2" hits
  [ -f "$logfile" ] || return 0
  # WINDOW SIZE BUG FOUND LIVE 2026-11-28: a single real crash's own traceback
  # (the "Traceback (most recent call last):" header plus the final exception
  # line) spans ~15-20 lines by itself on this codebase's deepest call stacks.
  # The original `tail -n 40` could therefore never contain more than ~2 full
  # crash cycles (~4 hits) -- the `-ge 8` threshold was mathematically
  # unreachable no matter how severely a lane crash-looped. Confirmed against
  # the real 2026-11-27 BoardIntegrityError incident: tail -n 40 on that log
  # scored 3 hits; tail -n 300 on the same window scored 35. 300 lines holds
  # comfortably more than 8 hits' worth of real crashes while still requiring
  # several genuine failures (not one transient blip) to trip the alert.
  hits=$(tail -n 300 "$logfile" 2>/dev/null | grep -cE 'BoardIntegrityError|Traceback \(most recent call last\)')
  if [ "${hits:-0}" -ge 8 ]; then
    # Only write one alert per hour per wrapper -- don't spam the alert log
    # itself into the same kind of noise this is meant to fix.
    local marker="$ROOT/logs/.alerted_${name}"
    local now; now=$(date +%s)
    local last=0
    [ -f "$marker" ] && last=$(cat "$marker" 2>/dev/null || echo 0)
    if [ $((now - last)) -ge 3600 ]; then
      echo "$(date -u +%FT%TZ) STUCK $name: ${hits}/300 recent log lines show BoardIntegrityError/Traceback -- check $logfile" >> "$ALERTLOG"
      echo "$now" > "$marker"
    fi
  fi
}

if ! alive "backfill_gis_attrs_boardwide.py"; then
  relaunch gis_attrs_boardwide \
    "cd '$ROOT' && for i in \$(seq 1 150); do $PY scripts/backfill_gis_attrs_boardwide.py --allow-large --max-rows 3000 >> logs/gis_attrs_backfill_continuous.log 2>&1; sleep 15; done"
fi
check_stuck gis_attrs_boardwide "$ROOT/logs/gis_attrs_backfill_continuous.log"

if ! alive "backfill_mecklenburg_gis_attrs.py"; then
  relaunch meck_gis_attrs \
    "cd '$ROOT' && for i in \$(seq 1 300); do BOARD_PATCH_ALLOW_LARGE=1 $PY scripts/backfill_mecklenburg_gis_attrs.py --allow-large --max-rows 3000 >> logs/backfill_meck_gis_attrs_continuous.log 2>&1; sleep 15; done"
fi
check_stuck meck_gis_attrs "$ROOT/logs/backfill_meck_gis_attrs_continuous.log"

if ! alive "backfill_mecklenburg_code_enforcement.py"; then
  relaunch meck_code_enforcement \
    "cd '$ROOT' && for i in \$(seq 1 300); do BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 $PY scripts/backfill_mecklenburg_code_enforcement.py --batch-size 300 --max-batches 1 >> logs/backfill_meck_codeenf_continuous.log 2>&1; sleep 15; done"
fi
check_stuck meck_code_enforcement "$ROOT/logs/backfill_meck_codeenf_continuous.log"

if ! alive "backfill_mecklenburg_tax.py"; then
  relaunch meck_tax \
    "cd '$ROOT' && for i in \$(seq 1 300); do BOARD_PATCH_ALLOW_LARGE=1 BOARD_APPEND_ALLOW_LARGE=1 $PY scripts/backfill_mecklenburg_tax.py --rounds 3 >> logs/backfill_meck_tax_continuous.log 2>&1; sleep 15; done"
fi
check_stuck meck_tax "$ROOT/logs/backfill_meck_tax_continuous.log"

if ! alive "run_comps_sweep.sh"; then
  relaunch comps_sweep "bash '$ROOT/scripts/run_comps_sweep.sh'"
fi

if ! alive "backfill_deed_chain_v2.py"; then
  relaunch deed_chain_v2 \
    "cd '$ROOT' && for i in \$(seq 1 20); do $PY scripts/backfill_deed_chain_v2.py --allow-large >> logs/manual_deed_chain_v2_run.log 2>&1; sleep 20; done"
fi
check_stuck deed_chain_v2 "$ROOT/logs/manual_deed_chain_v2_run.log"

if ! alive "verification_sweep.py --signal tax_lien"; then
  relaunch tax_lien \
    "cd '$ROOT' && HANDOFF_PUSH=0 $PY scripts/verification_sweep.py --signal tax_lien >> logs/manual_tax_lien_relaunch.log 2>&1"
fi
