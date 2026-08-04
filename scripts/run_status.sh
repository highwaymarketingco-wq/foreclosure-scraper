#!/bin/bash
# Plain-English status of the foreclosure engine, shown in a dialog.
# The run has no window on purpose (it is backgrounded so it survives closing
# things), so this is how you look at it.
REPO="$HOME/foreclosure-scraper"
cd "$REPO" 2>/dev/null || {
  osascript -e 'display alert "Foreclosure Engine" message "Could not find ~/foreclosure-scraper."' >/dev/null 2>&1
  exit 1; }

LOG=$(ls -t logs/local-run-*.log 2>/dev/null | head -1)

if pgrep -f "run_local.sh|-m foreclosure_scraper" >/dev/null 2>&1; then
  PID=$(pgrep -f "\-m foreclosure_scraper" | tail -1)
  ELAPSED=$(ps -o etime= -p "$PID" 2>/dev/null | tr -d ' ')
  DONE=$(grep -ac '"event": "scraper.ok"' "$LOG" 2>/dev/null || echo 0)
  ERRS=$(grep -ac '"event": "scraper.error"' "$LOG" 2>/dev/null || echo 0)
  LASTW=$(stat -f '%Sm' -t '%-I:%M %p' "$LOG" 2>/dev/null)
  # "stalled" = log untouched for >20 min while the process is still alive
  NOWS=$(date +%s); LOGS=$(stat -f '%m' "$LOG" 2>/dev/null || echo "$NOWS")
  QUIET=$(( (NOWS - LOGS) / 60 ))
  if [ "$QUIET" -gt 20 ]; then
    HEALTH="⚠️  No new activity for ${QUIET} minutes — it may be stuck on a slow source."
  else
    HEALTH="✅ Healthy — still writing to its log."
  fi
  MSG="RUNNING for ${ELAPSED}.

Sources finished: ${DONE}
Errors so far:    ${ERRS}
Last activity:    ${LASTW}

${HEALTH}

It takes several hours and has no window on purpose, so you can close things and keep working. You'll get a notification when it finishes."
  BTN='{"Show log", "OK"}'
else
  BOARD=$(ls -l docs/listings.json.gz 2>/dev/null | awk '{print $6, $7, $8}')
  TOTAL=$(python3 -c "import json;print(f\"{json.load(open('docs/run_meta.json'))['total']:,}\")" 2>/dev/null || echo "unknown")
  if [ -n "$LOG" ]; then
    FIN=$(grep -aq "web_artifact.written" "$LOG" 2>/dev/null && echo yes || echo no)
    LASTW=$(stat -f '%Sm' -t '%b %-d at %-I:%M %p' "$LOG" 2>/dev/null)
    if [ "$FIN" = "yes" ]; then
      OUT="The last run FINISHED and published."
    else
      OUT="⚠️  The last run STOPPED before publishing (last activity ${LASTW}). Usually that means the Mac slept or restarted."
    fi
  else
    OUT="No run log found yet."
  fi
  MSG="NOT RUNNING.

${OUT}

Dashboard last updated: ${BOARD}
Leads on the dashboard:  ${TOTAL}

To start one, double-click \"Run Foreclosure Engine\" on your Desktop."
  BTN='{"Show log", "OK"}'
fi

CHOICE=$(osascript <<OSA 2>/dev/null
try
  set r to button returned of (display dialog "$MSG" buttons $BTN default button "OK" with title "Foreclosure Engine" with icon note)
  return r
end try
OSA
)
[ "$CHOICE" = "Show log" ] && [ -n "$LOG" ] && open -a Console "$REPO/$LOG" 2>/dev/null
exit 0
