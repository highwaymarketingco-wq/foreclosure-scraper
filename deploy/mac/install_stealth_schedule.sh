#!/usr/bin/env bash
# Mac side of the cloud split — schedule the stealth-source hand-off (launchd).
#
# Runs scripts/run_stealth_sources.py daily at 06:00 LOCAL: it runs only the 39
# residential-IP stealth scrapers and pushes docs/handoff/stealth_leads.json for
# the Oracle VM to ingest. Lightweight (no board load) — safe on 8 GB. If the
# Mac is asleep at 06:00, launchd fires the missed run once at next wake.
#
# Usage:
#   bash deploy/mac/install_stealth_schedule.sh          # install + load
#   bash deploy/mac/install_stealth_schedule.sh remove   # unload + remove
#
# Verify:        launchctl list | grep stealth-handoff
# Run once now:  launchctl start com.highway.foreclosure.stealth-handoff
# Watch log:     tail -f logs/stealth-handoff-*.log
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="com.highway.foreclosure.stealth-handoff"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

UV_BIN="$(command -v uv || echo "$HOME/.local/bin/uv")"
UV_DIR="$(dirname "$UV_BIN")"

if [[ "${1:-}" == "remove" ]]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $LABEL"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>cd "$ROOT" &amp;&amp; exec "$UV_BIN" run python scripts/run_stealth_sources.py</string>
  </array>

  <!-- Daily at 06:00 local (before the VM's default 07:00 UTC run). Missed
       runs (Mac asleep) fire once at next wake. -->
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>6</integer>
    <key>Minute</key><integer>0</integer>
  </dict>

  <key>WorkingDirectory</key>
  <string>$ROOT</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$UV_DIR:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>

  <key>StandardOutPath</key>
  <string>$ROOT/logs/stealth-handoff.log</string>
  <key>StandardErrorPath</key>
  <string>$ROOT/logs/stealth-handoff.log</string>

  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed $LABEL (daily 06:00 local)."
echo "Run once now:  launchctl start $LABEL"
echo "Watch log:     tail -f $ROOT/logs/stealth-handoff.log"
