#!/usr/bin/env bash
# Install the systemd timer that runs the VM pipeline (vm_run.sh) daily.
# Generates the unit files for the CURRENT user/paths (no hardcoded ubuntu/home). Re-runnable.
#
# NOT INSTALLED (2026-10-06): the owner's rule is no VM run until a gated run is proven: install
# this only after a `vm_run.sh --stop-before-publish` run has been reviewed and published with
# `vm_resume.sh --publish-only` (docs/HANDOFF.md item 72). It is a dry run unless --install:
#
#   bash deploy/oracle/install_timer.sh                       # print the units, change nothing
#   bash deploy/oracle/install_timer.sh --install             # write + enable (daily 13:00 UTC)
#   RUN_AT="14:00" bash deploy/oracle/install_timer.sh --install   # custom time (UTC)
#
# THE CHOICES (2026-10-06)
#   * 13:00 UTC, not 07:00. vm_run.sh ingests the Mac's stealth hand-off, which the Mac starts at
#     6:00 AM ET and finishes around 7:40 ET: 11:40 UTC in EDT, 12:40 UTC in EST. 07:00 UTC
#     (3:00 ET) ran on the PREVIOUS day's hand-off. 13:00 UTC is 9:00 EDT / 8:00 EST: after the
#     hand-off in both, with 20 minutes to spare in winter.
#   * TimeoutStartSec=30h, not 6h. 6 h killed every real run: the 10/5 full run took ~18 h to its
#     last step at 270K rows. The next board is 320-355K rows (up to +31%), and the steps after
#     the (3 h capped) scrape scale with rows: ~18 h x 1.31 = ~23.6 h, plus the publish (~20 min
#     for publish_tail at 355K, cf372926) and the commit + push of ~0.5 GB: ~24.5 h. 30 h is ~20%
#     over that and still stops a wedged run (the 8/14 run hung 16 h on one retry loop) within a
#     day and a quarter. While a run is still active, systemd does not start another one: the next
#     day's trigger is skipped, never stacked. (The board lock's own limit is 72 h.)
#   * The service PUBLISHES (vm_run.sh without --stop-before-publish). A stop-before-publish run
#     publishes nothing and leaves a pre_publish checkpoint, and vm_run.sh refuses to start over a
#     checkpoint waiting to be published: unattended, the timer would produce one unpublished board
#     and then refuse every night until a human acts. Review is the gated launch's job; the timer is
#     for after it. Every run still has the memory watchdog, the preflights (disk, reference data,
#     a pending checkpoint) and the count-drop alert, and a failed run publishes nothing.
#   * Swap must survive a reboot first: Persistent=true runs a missed day right after boot, and
#     the 4 GB swapfile is not in /etc/fstab. --install refuses until it is (ALLOW_NO_FSTAB_SWAP=1
#     overrides).
set -euo pipefail

DIR="$(cd "$(dirname "$0")/../.." && pwd)"
RUN_AT="${RUN_AT:-13:00}"
UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
INSTALL=0
for a in "$@"; do
  case "$a" in
    --install) INSTALL=1 ;;
    *) echo "install_timer.sh: unknown argument: $a" >&2; exit 64 ;;
  esac
done
if ! [[ "$RUN_AT" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
  echo "install_timer.sh: RUN_AT must be HH:MM (UTC), got '$RUN_AT'" >&2; exit 64
fi

SERVICE="[Unit]
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
TimeoutStartSec=30h
"

TIMER="[Unit]
Description=Run the foreclosure engine daily

[Timer]
OnCalendar=*-*-* ${RUN_AT}:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
"

if [[ "$INSTALL" != "1" ]]; then
  echo "# DRY RUN (nothing written). Pass --install to write and enable these units."
  echo "# ---- $UNIT_DIR/foreclosure.service"
  printf '%s' "$SERVICE"
  echo "# ---- $UNIT_DIR/foreclosure.timer  (daily at ${RUN_AT} UTC)"
  printf '%s' "$TIMER"
  exit 0
fi

if [[ "${ALLOW_NO_FSTAB_SWAP:-0}" != "1" ]] && ! awk '$1 !~ /^#/ && $3 == "swap" {f=1} END{exit !f}' "${FSTAB:-/etc/fstab}"; then
  echo "install_timer.sh: no swap entry in ${FSTAB:-/etc/fstab}: a reboot drops the swapfile and" \
       "the timer's catch-up run would start without it. Add it first:" >&2
  echo "  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab" >&2
  exit 1
fi

echo "==> writing $UNIT_DIR/foreclosure.service"
printf '%s' "$SERVICE" | sudo tee "$UNIT_DIR/foreclosure.service" >/dev/null
echo "==> writing $UNIT_DIR/foreclosure.timer  (daily at ${RUN_AT} UTC)"
printf '%s' "$TIMER" | sudo tee "$UNIT_DIR/foreclosure.timer" >/dev/null

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
