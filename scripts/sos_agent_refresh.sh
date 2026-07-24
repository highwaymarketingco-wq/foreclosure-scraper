#!/bin/zsh
# Daily 2pm NC SOS registered-agent pass: advance the entity-contact frontier
# by ~40 new NC LLC leads/day (gentle on sosnc.gov — the enricher now skips
# already-resolved names and back-off is enforced by a fast circuit breaker).
# Runs AFTER the noon lrcpwa pass, guards against any active board-writer, and
# commits ONLY when new contacts actually landed (a Cloudflare-walled run bails
# fast with 0 changes and must not create an empty commit).
set -uo pipefail
ROOT="$HOME/foreclosure-scraper"; cd "$ROOT" || exit 1
LOG="/tmp/sos_agent_refresh.log"
exec >> "$LOG" 2>&1
echo "=== sos_agent_refresh $(date) ==="

# one board-writer at a time — skip if a full run / merge / lrcpwa pass is active
if pgrep -f "merge_today_sources.py" >/dev/null \
   || pgrep -f "foreclosure_scraper.__main__|-m foreclosure_scraper|run_local.sh" >/dev/null \
   || pgrep -f "lrcpwa_refresh.py" >/dev/null; then
  echo "board-writer active — skipping this run"; exit 0
fi

export SOS_AGENT=1
export SOS_AGENT_MAX_CHECK="${SOS_AGENT_MAX_CHECK:-40}"
export SOS_AGENT_BREAKER_FAILS="${SOS_AGENT_BREAKER_FAILS:-6}"
/Users/cashhigh/.local/bin/uv run python scripts/sos_agent_refresh.py || { echo "pass failed rc=$?"; exit 1; }

# commit ONLY if the board data changed (not run_meta's timestamp) — a walled
# run rewrites listings.json byte-identical and must not commit.
git add docs/listings.json docs/listings.json.gz \
        docs/listings_detail.json docs/listings_detail.json.gz
if ! git diff --cached --quiet -- docs/listings.json docs/listings_detail.json; then
  git add docs/run_meta.json
  git commit -q -m "Scheduled SOS pass: +NC entity registered-agent contacts

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>" && git push 2>&1 | tail -1
  echo "committed + pushed"
else
  echo "no new contacts (sosnc.gov may be rate-limited) — no commit"
  git reset -q
fi
echo "=== done $(date) ==="
