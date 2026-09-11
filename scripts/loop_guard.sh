#!/bin/zsh
# Resource gate for the weekend loop. Prints GO or WAIT plus the numbers.
# The machine is an 8GB Air; one heavy job at a time is the rule.
free_mb=$(vm_stat | awk 'NR==2{printf "%.0f",$3*16384/1048576}')
swap_used=$(sysctl -n vm.swapusage | sed -E 's/.*used = ([0-9.]+)M.*/\1/')
disk_free_gb=$(df -g /System/Volumes/Data | tail -1 | awk '{print $4}')
# Count JOBS, not processes: `uv run` spawns a child, and grep counts itself.
heavy=$(pgrep -f "foreclosure-scraper/.venv/bin/python3" | wc -l | tr -d " ")
echo "free_mb=$free_mb swap_used_mb=${swap_used%.*} disk_free_gb=$disk_free_gb heavy_jobs=$heavy"
# Thresholds: keep 1.5GB of headroom, 8GB of disk, and at most ONE heavy job.
if [ "${swap_used%.*}" -gt 3500 ] || [ "$disk_free_gb" -lt 8 ] || [ "$heavy" -gt 1 ]; then
  echo "WAIT"
else
  echo "GO"
fi
