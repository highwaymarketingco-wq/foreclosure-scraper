#!/bin/zsh
# Noon land-records refresh: fill lrcpwa addresses/values/photos deferred by the
# API rate limit, recompute tags, commit + push. Guards against a running weekly.
set -uo pipefail
ROOT="$HOME/foreclosure-scraper"; cd "$ROOT" || exit 1
LOG="/tmp/lrcpwa_refresh.log"
exec >> "$LOG" 2>&1
echo "=== lrcpwa_refresh $(date) ==="
# one board-writer at a time — skip if a full run / merge is active.
# Unescaped alternation: pgrep -f uses ERE, where `\|` is a LITERAL pipe (it
# matched nothing, so this guard silently never fired — double board-writer +
# git race every Tue/Fri). Matches the working sos_agent_refresh.sh pattern.
if pgrep -f "merge_today_sources.py" >/dev/null \
   || pgrep -f "foreclosure_scraper.__main__|-m foreclosure_scraper|run_local.sh" >/dev/null; then
  echo "board-writer active — skipping this noon run"; exit 0
fi
/Users/cashhigh/.local/bin/uv run python scripts/lrcpwa_refresh.py || { echo "pass failed rc=$?"; exit 1; }
# commit + push the refreshed board (+ any new photos)
git add docs/listings.json docs/listings.json.gz \
        docs/listings_detail.json docs/listings_detail.json.gz \
        docs/run_meta.json docs/parcel_photos 2>/dev/null
if ! git diff --cached --quiet; then
  git commit -q -m "Scheduled land-records refresh: lrcpwa addresses/values/photos + tags

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>" && git push 2>&1 | tail -1
  echo "committed + pushed"
else
  echo "no board changes to commit"
fi
echo "=== done $(date) ==="
