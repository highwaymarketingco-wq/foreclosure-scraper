#!/usr/bin/env bash
# Install the weekly local run as a launchd job (macOS).
#
# Runs scripts/run_local.sh every Tuesday at 09:00 LOCAL time. If the Mac is
# asleep/off at 09:00, launchd runs the job at the next wake (RunAtLoad is
# false, but StartCalendarInterval fires a missed run once on wake).
#
# Usage:
#   bash scripts/install_local_schedule.sh          # install + load
#   bash scripts/install_local_schedule.sh remove   # unload + remove
#
# After install, verify:   launchctl list | grep foreclosure
# Run once now:            launchctl start com.highway.foreclosure.weekly
# Watch the log:           tail -f logs/local-run-*.log
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.highway.foreclosure.weekly"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
RUNNER="$ROOT/scripts/run_local.sh"

# Absolute path to uv so launchd (minimal PATH) can find it.
UV_BIN="$(command -v uv || echo "$HOME/.local/bin/uv")"
UV_DIR="$(dirname "$UV_BIN")"

if [[ "${1:-}" == "remove" ]]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $LABEL"
  exit 0
fi

chmod +x "$RUNNER"
mkdir -p "$HOME/Library/LaunchAgents"

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
    <string>$RUNNER</string>
  </array>

  <!-- Weekly: Tuesday (weekday 2) at 09:00 local. Missed runs (Mac asleep)
       fire once at next wake. -->
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>2</integer>
    <key>Hour</key><integer>9</integer>
    <key>Minute</key><integer>0</integer>
  </dict>

  <key>WorkingDirectory</key>
  <string>$ROOT</string>

  <!-- launchd runs with a minimal PATH; add uv + standard bins. -->
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$UV_DIR:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>

  <key>RunAtLoad</key>
  <false/>

  <key>StandardOutPath</key>
  <string>$ROOT/logs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$ROOT/logs/launchd.err.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "Installed $LABEL"
echo "  plist:  $PLIST"
echo "  runs:   Tuesdays 09:00 local (missed runs fire at next wake)"
echo ""
echo "Verify:        launchctl list | grep foreclosure"
echo "Run once now:  launchctl start $LABEL"
echo "Watch log:     tail -f $ROOT/logs/local-run-*.log"
