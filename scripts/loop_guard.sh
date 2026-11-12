#!/bin/zsh
# Resource gate for the weekend loop. Prints the numbers, then GO or WAIT.
#
# WHY THIS USES memory_pressure AND NOT SWAP TOTAL
#   The first version refused work whenever swap exceeded 3.5GB. On an 8GB Mac running
#   Claude, swap sits at 3-6GB as a matter of course -- macOS uses swap and compressed
#   memory liberally and a high swap TOTAL is not memory pressure. That threshold read
#   "busy" as "dying" and blocked the unattended runner for ~29 hours across a weekend
#   while macOS itself reported 61% of memory free. Measure what the OS measures.
free_pct=$(memory_pressure 2>/dev/null | sed -nE 's/.*free percentage: ([0-9]+)%.*/\1/p' | tail -1)
[ -z "$free_pct" ] && free_pct=50          # if the tool is unavailable, do not block
swap_used=$(sysctl -n vm.swapusage | sed -E 's/.*used = ([0-9.]+)M.*/\1/')
disk_free_gb=$(df -g /System/Volumes/Data | tail -1 | awk '{print $4}')
heavy=$(pgrep -f "foreclosure-scraper/.venv/bin/python3" | wc -l | tr -d " ")

echo "mem_free_pct=$free_pct swap_used_mb=${swap_used%.*} disk_free_gb=$disk_free_gb heavy_jobs=$heavy"

# Proceed unless the OS says memory is genuinely tight, the disk is nearly full, or a
# heavy job is already running. One heavy job at a time remains the rule.
if [ "$free_pct" -lt 15 ] || [ "$disk_free_gb" -lt 8 ] || [ "$heavy" -gt 1 ]; then
  echo "WAIT"
else
  echo "GO"
fi
