#!/bin/bash
# Drive the related-filings enricher in back-to-back batches until the queue is dry.
# Each batch loads the board, fetches, writes, and exits, so a crash costs one batch
# and the logs/ checkpoint resumes. Batches are large to amortise the 600MB board write.
cd "$(dirname "$0")/.." || exit 1
for i in $(seq 1 12); do
  echo "=== batch $i  $(date) ==="
  # SIDECAR ONLY -- no --write-board. The 2026-09-10 run died at batch 5 after ~3h
  # of work because the scheduled run_daily_vision.sh held the board lock and the
  # batch-end write raised BoardLockBusy, which this loop then treated as fatal.
  # The network fetching never needed that lock; only the write did. The sidecar
  # (logs/liensnc_related.jsonl, appended per fetch) is the durable store, so the
  # harvest now runs to completion regardless of what else holds the board, and the
  # board is updated afterwards in ONE pass by merge_liensnc_related_sidecar.py.
  uv run python scripts/liensnc_related_filings.py --limit 3000 --delay 1.1
  rc=$?
  echo "=== batch $i exit=$rc  $(date) ==="
  # A failed batch is no longer fatal: the sidecar means a batch costs at most the
  # fetches it had not yet made, and the next batch resumes from what is captured.
  if [ $rc -ne 0 ]; then
    echo "batch $i failed (rc=$rc) -- sidecar is intact, continuing to next batch"
    sleep 20
  fi
  grep -q "nothing to do" /dev/null 2>&1
  # Count from the SIDECAR, the durable store -- the checkpoint once claimed 1,508
  # entries were captured whose data had been stripped at publish.
  remaining=$(python3 -c "
import pathlib
p=pathlib.Path('logs/liensnc_related.jsonl')
n=sum(1 for _ in p.open()) if p.exists() else 0
print(18932-n)" 2>/dev/null || echo 0)
  echo "remaining: $remaining"
  [ "$remaining" -le 0 ] && { echo "queue dry"; break; }
done
echo "=== driver done $(date) ==="
