#!/bin/zsh
# Weekend harvester. Runs UNATTENDED, one heavy job at a time, forever until told to stop.
#
# DESIGN RULE: this script only HARVESTS to files under logs/. It never writes the board.
# Board writes need a dry-run read and a judgment call, so they stay with the supervised
# loop. A runaway that only ever appends JSON to logs/ cannot corrupt the dashboard.
#
#   start :  nohup ./scripts/weekend_runner.sh > logs/weekend_runner.log 2>&1 &
#   stop  :  touch logs/STOP_WEEKEND        (checked before every job)
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
STOP=logs/STOP_WEEKEND
rm -f "$STOP"

say() { echo "[$(date '+%m-%d %H:%M:%S')] $*"; }

gate() {
  # Wait until the machine can take a heavy job. Returns when clear.
  while :; do
    [ -f "$STOP" ] && return 1
    local out; out=$(./scripts/loop_guard.sh 2>/dev/null)
    case "$out" in (*GO*) return 0;; esac
    say "gate WAIT — $(echo "$out" | head -1)"
    sleep 120
  done
}

#: A marker only counts as DONE if it holds real records. The first version checked
#: only that the file existed -- and skipped the Catalis job because the 4-byte "[]"
#: left by the rate-limited run was sitting there. An empty output counting as success
#: is the same silent-skip class as every other bug found this week.
MIN_MARKER_BYTES=${MIN_MARKER_BYTES:-2000}

run_job() {           # run_job <name> <marker-file> <command...>
  local name=$1 marker=$2; shift 2
  if [ -f "$marker" ]; then
    local sz; sz=$(wc -c < "$marker" | tr -d ' ')
    if [ "$sz" -ge "$MIN_MARKER_BYTES" ]; then
      say "skip $name (have $marker, ${sz}B)"; return
    fi
    say "redo $name — $marker exists but is only ${sz}B, that is not a harvest"
    rm -f "$marker"
  fi
  gate || return 1
  say "START $name"
  if "$@"; then say "OK    $name"; else say "FAIL  $name (exit $?)"; fi
}

PY=".venv/bin/python3"

while :; do
  [ -f "$STOP" ] && { say "STOP file present — exiting"; break; }

  # 1. Catalis Pickens — REMOVED 2026-09-11. The host escalated from HTTP 429 to a hard
  #    403 block after we paced to 8s, ran concurrency 1 and honored every Retry-After.
  #    A 403 arriving after that is the host declining, and working around it is bypass
  #    behaviour the operator has explicitly ruled out. Do not re-enable without a
  #    deliberate decision; the block is recorded in the loop queue.
  false && run_job "catalis-pickens" logs/catalis_pickens_full.json \
    env CATALIS_ROLL_BUDGET=4000 CATALIS_ROLL_PACE_S=8 CATALIS_ROLL_CONCURRENCY=1 \
    $PY -c "
import asyncio,json,sys
sys.path.insert(0,'src')
from foreclosure_scraper.scrapers.counties_sc.sc_catalis_delinquent_roll import SCCatalisDelinquentRoll
from foreclosure_scraper.web_artifact import _to_dict
rows=asyncio.run(SCCatalisDelinquentRoll().fetch())
rows=list(rows)
json.dump([_to_dict(r) for r in rows], open('logs/catalis_pickens_full.json','w'))
print('pickens rows', len(rows))"

  # 2. Greenville MIE — full 772 adverts.
  run_job "greenville-mie" logs/greenville_mie_full_v2.json \
    env GREENVILLE_MIE_MAX=800 \
    $PY -c "
import asyncio,json,sys
sys.path.insert(0,'src')
from foreclosure_scraper.scrapers.counties_sc.greenville_mie_adverts import GreenvilleMIEAdverts
from foreclosure_scraper.web_artifact import _to_dict
rows=list(asyncio.run(GreenvilleMIEAdverts().fetch()))
json.dump([_to_dict(r) for r in rows], open('logs/greenville_mie_full_v2.json','w'))
print('mie rows', len(rows))"

  # 3. SC DEW lien registry — full export, direct HTTP.
  run_job "sc-dew-liens" logs/sc_dew_full.json \
    $PY -c "
import asyncio,json,sys
sys.path.insert(0,'src')
from foreclosure_scraper.scrapers.counties_sc.sc_dew_lien_registry import SCDEWLienRegistry
from foreclosure_scraper.web_artifact import _to_dict
s=SCDEWLienRegistry(); s.max_rows=40000
rows=list(asyncio.run(s.fetch()))
json.dump([_to_dict(r) for r in rows], open('logs/sc_dew_full.json','w'))
print('dew rows', len(rows))"

  say "cycle complete — sleeping 30m before re-checking for new work"
  for i in $(seq 1 15); do [ -f "$STOP" ] && break; sleep 120; done
done
say "runner exited"
