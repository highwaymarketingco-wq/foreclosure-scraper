#!/bin/bash
# Scheduled Tue/Fri POPUP. Instead of a silent auto-run (which was missed whenever
# the Mac was asleep at 9:30), this walks you through the two things a refresh needs,
# with buttons — no terminal. If the Mac was asleep at 9:30, macOS fires this at the
# next wake, so the popup is waiting when you open the laptop.
#
#   Step 1 — the manual court sources (SC PublicIndex / NC eCourts you save by hand)
#   Step 2 — the full engine run
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
REPO="$HOME/foreclosure-scraper"
DROP="$HOME/Desktop/Court Pages (drop here)"
GUIDE="$DROP/_READ ME — how to refresh court sources.txt"

# This popup used to leave NO trace: no log line, always `exit 0`, so nobody could tell
# whether it appeared, was answered, or was ignored while the "weekly" full run stopped
# landing (audit O2/O10). It now writes one log line per decision and one job event.
mkdir -p "$REPO/logs"
PLOG="$REPO/logs/prompt_run.log"
plog() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$PLOG"; }
ROOT="$REPO"
. "$REPO/scripts/job_event.sh"
JOB_EVENT_ROOT="$REPO"
job_event_begin prompt_run
trap 'job_event_finalize' EXIT
plog "popup fired ($(date +%a))"

# If a run is already going (e.g. you pressed the Desktop button), don't nag.
if pgrep -f "run_local.sh|-m foreclosure_scraper" >/dev/null 2>&1; then
  plog "run already active - popup not shown"
  job_event_end no_change "" "run_already_active"
  exit 0
fi
mkdir -p "$DROP"

# ---- Step 1: the manual court sources ----
while true; do
  s1=$(osascript <<'OSA' 2>/dev/null
try
  set r to button returned of (display dialog "Weekly foreclosure refresh — Step 1 of 2: the court sources.

If you've saved the latest SC PublicIndex / NC eCourts pages into the drop folder, click \"Ingest what I saved.\"

Not sure what to save? Click \"Open folder + guide.\"" buttons {"Open folder + guide", "Skip", "Ingest what I saved"} default button "Ingest what I saved" with title "Foreclosure Engine" with icon note giving up after 7200)
  return r
end try
OSA
)
  if [ "$s1" = "Open folder + guide" ]; then
    open "$DROP" >/dev/null 2>&1
    [ -f "$GUIDE" ] && open "$GUIDE" >/dev/null 2>&1
    continue   # re-show the step-1 dialog after they've looked
  fi
  break
done
plog "step 1 answer: '${s1:-<no answer within 7200s>}'"
if [ "$s1" = "Ingest what I saved" ]; then
  bash "$REPO/scripts/ingest_saved.sh"   # runs now, before the full run; refuses if a run is active
  plog "step 1 ingest finished rc=$?"
fi

# ---- Step 2: the full run ----
s2=$(osascript <<'OSA' 2>/dev/null
try
  set r to button returned of (display dialog "Step 2 of 2: run the full engine now?

It takes several hours; you'll get a notification when it's done and you can keep using your Mac." buttons {"Not now", "Run now"} default button "Run now" with title "Foreclosure Engine" with icon note giving up after 7200)
  return r
end try
OSA
)
plog "step 2 answer: '${s2:-<no answer within 7200s>}'"
if [ "$s2" = "Run now" ]; then
  bash "$REPO/scripts/gui_run.sh"
  plog "step 2: full run launched via gui_run.sh rc=$?"
  job_event_end ok "" "full_run_started"
elif [ -z "$s2" ]; then
  job_event_end no_change "" "popup_unanswered"
else
  job_event_end no_change "" "declined"
fi
exit 0
