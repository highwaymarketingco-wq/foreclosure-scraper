#!/usr/bin/env bash
# Install the systemd timer that runs the VM pipeline daily.
# Generates the unit files for the CURRENT user/paths (no hardcoded ubuntu/home),
# then enables the timer. Re-runnable.
#
#   bash deploy/oracle/install_timer.sh                 # default: 07:00 UTC daily
#   RUN_AT="03:00" bash deploy/oracle/install_timer.sh  # custom time (UTC)
set -euo pipefail

DIR="$(cd "$(dirname "$0")/../.." && pwd)"
RUN_AT="${RUN_AT:-07:00}"
UNIT_DIR="/etc/systemd/system"

echo "==> writing $UNIT_DIR/foreclosure.service"
sudo tee "$UNIT_DIR/foreclosure.service" >/dev/null <<EOF
[Unit]
Description=Foreclosure engine — datacenter (VM) run
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=$(id -un)
WorkingDirectory=$DIR
Environment=HOME=$HOME
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/bin/env bash $DIR/deploy/oracle/vm_run.sh
TimeoutStartSec=6h
EOF

echo "==> writing $UNIT_DIR/foreclosure.timer  (daily at ${RUN_AT} UTC)"
sudo tee "$UNIT_DIR/foreclosure.timer" >/dev/null <<EOF
[Unit]
Description=Run the foreclosure engine daily

[Timer]
OnCalendar=*-*-* ${RUN_AT}:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now foreclosure.timer

echo ""
echo "==> installed. Status:"
systemctl status foreclosure.timer --no-pager | head -6 || true
echo ""
echo "    Next scheduled run:  systemctl list-timers foreclosure.timer --no-pager"
echo "    Run once now:        sudo systemctl start foreclosure.service"
echo "    Watch the log:       journalctl -u foreclosure.service -f"
echo "    Or the run log:      tail -f $DIR/logs/vm-run-*.log"
