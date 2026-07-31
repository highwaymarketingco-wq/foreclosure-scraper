#!/bin/bash
# One-click GUI runner for the full foreclosure engine (no terminal needed).
# Safe to press twice: if a run is already going it just tells you and leaves it
# alone — it NEVER starts a second run. Notifies on start + finish.
REPO="$HOME/foreclosure-scraper"
cd "$REPO" 2>/dev/null || { osascript -e 'display alert "Foreclosure Engine" message "Could not find ~/foreclosure-scraper."'; exit 1; }

if pgrep -f "run_local.sh|-m foreclosure_scraper|merge_today_sources" >/dev/null 2>&1; then
  osascript -e 'display notification "A run is already in progress — leaving it alone." with title "Foreclosure Engine"' 2>/dev/null
  exit 0
fi
# Also never start a full run while a court-page ingest is mid-write (both write the board).
if pgrep -f "ingest_saved.sh|ingest_publicindex_files|ingest_fresh_court_leads|parse_nc_ecourts" >/dev/null 2>&1; then
  osascript -e 'display notification "A court-page ingest is finishing — try the run again in a minute." with title "Foreclosure Engine"' 2>/dev/null
  exit 0
fi

mkdir -p logs
osascript -e 'display notification "Starting the full run. It takes several hours — you can close this and keep working." with title "Foreclosure Engine started"' 2>/dev/null

# Run caffeinated (so the Mac cannot sleep through it) in the background, then
# notify when it finishes. nohup + & so closing the app does not kill the run.
nohup bash -c '
  cd "'"$REPO"'" || exit 1
  caffeinate -is bash scripts/run_local.sh >> logs/gui-run.log 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    osascript -e "display notification \"Run finished — dashboard updated.\" with title \"Foreclosure Engine done\"" 2>/dev/null
  else
    osascript -e "display notification \"Run ended (code $rc). It may just be a low-count guard; check the dashboard.\" with title \"Foreclosure Engine\"" 2>/dev/null
  fi
' >/dev/null 2>&1 &
exit 0
