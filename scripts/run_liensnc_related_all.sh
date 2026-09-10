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
  remaining=$(python3 -c "
import json
d=json.load(open('logs/liensnc_related_checkpoint.json'))
print(18932-len(d['done']))" 2>/dev/null || echo 0)
  echo "remaining: $remaining"
  [ "$remaining" -le 0 ] && { echo "queue dry"; break; }
done
echo "=== driver done $(date) ==="
