#!/bin/bash
# Auto-rerun board enrichment until coverage is sufficient.
# Runs enrich_board.py back-to-back, logging each run.
# Kills after N runs or when dot_ocr coverage is sufficient.

cd /Users/cashhigh/foreclosure-scraper
export PATH="$HOME/bin:$PATH"
export PYTHONPATH=~/foreclosure-scraper/src:~/foreclosure-scraper/.venv/lib/python3.12/site-packages:$PYTHONPATH

MAX_RUNS=5
RUN=1
LOGDIR="/tmp/board_autoruns"
mkdir -p "$LOGDIR"

while [ $RUN -le $MAX_RUNS ]; do
    LOG="$LOGDIR/run_${RUN}_$(date +%Y%m%d_%H%M%S).log"
    echo "=== RUN $RUN/$MAX_RUNS starting $(date) ===" | tee -a "$LOG"
    python3.12 scripts/enrich_board.py 2>&1 | tee -a "$LOG"
    EXIT=$?
    echo "=== RUN $RUN exited with code $EXIT at $(date) ===" | tee -a "$LOG"
    
    # Check if we should continue — count dot_ocr coverage
    OCR_DONE=$(python3.12 -c "
import json, gzip
try:
    with gzip.open('docs/listings.json.gz','rt') as f:
        data = json.load(f)
    n = sum(1 for li in data if li.get('raw',{}).get('doc_ocr') is not None)
    print(n)
except: print(0)
" 2>/dev/null)
    echo "dot_ocr coverage: $OCR_DONE listings" | tee -a "$LOG"
    
    # If dot_ocr is > 12000 (out of ~14275 eligible), we're done
    if [ "$OCR_DONE" -gt 12000 ]; then
        echo "Sufficient dot_ocr coverage ($OCR_DONE). Stopping." | tee -a "$LOG"
        break
    fi
    
    RUN=$((RUN+1))
    echo "Waiting 10s before next run..." | tee -a "$LOG"
    sleep 10
done

echo "=== ALL RUNS COMPLETE at $(date) ===" | tee -a "$LOGDIR/final.log"
