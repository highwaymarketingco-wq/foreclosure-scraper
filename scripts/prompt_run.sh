#!/bin/bash
# Scheduled POPUP for the Tue/Fri run. Instead of silently auto-running (which
# missed whenever the Mac was asleep at 9:30), this shows a dialog with a "Run
# now" button. If the Mac was asleep at 9:30, macOS fires this the moment it next
# wakes, so the popup is waiting for you when you open the laptop.
REPO="$HOME/foreclosure-scraper"

# If a run is already going (e.g. you pressed the Desktop button), don't nag.
if pgrep -f "run_local.sh|-m foreclosure_scraper" >/dev/null 2>&1; then exit 0; fi

ans=$(osascript <<'OSA' 2>/dev/null
try
  set r to button returned of (display dialog "It's time for the scheduled foreclosure run (Tue/Fri)." & return & return & "Run it now? It takes several hours and you'll get a notification when it's done." buttons {"Not now", "Run now"} default button "Run now" with title "Foreclosure Engine" with icon note giving up after 7200)
  return r
end try
OSA
)
if [ "$ans" = "Run now" ]; then
  bash "$REPO/scripts/gui_run.sh"
fi
exit 0
