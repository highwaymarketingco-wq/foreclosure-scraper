#!/bin/bash
# Drive the related-filings enricher in back-to-back batches until the queue is dry.
# Each batch loads the board, fetches, writes, and exits, so a crash costs one batch
# and the logs/ checkpoint resumes. Batches are large to amortise the 600MB board write.
cd "$(dirname "$0")/.." || exit 1
for i in $(seq 1 12); do
  echo "=== batch $i  $(date) ==="
  uv run python scripts/liensnc_related_filings.py --limit 3000 --delay 1.1 --write-board
  rc=$?
  echo "=== batch $i exit=$rc  $(date) ==="
  [ $rc -ne 0 ] && { echo "batch failed, stopping"; break; }
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
