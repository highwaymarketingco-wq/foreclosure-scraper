#!/bin/zsh
# Weekly parcel-cache refresh — bulk re-download every configured county's parcel
# layer into local SQLite (completeness-verified, overwrite-in-place). Runs of the
# foreclosure engine just READ the cache via parcel_cache.lookup(); this is the only
# job that hits the county GIS in bulk. Parcels are slow-moving, so weekly is plenty.
#
# Overwrite-in-place = constant disk (~150-200 MB for the whole footprint, no growth,
# no cleanup needed). A truncated download is REJECTED (never replaces a good cache).
set -uo pipefail
ROOT="/Users/cashhigh/foreclosure-scraper"
cd "$ROOT" || exit 1
STAMP=$(date +%Y%m%dT%H%M%S)
echo "==> parcel-cache refresh $STAMP"
# use the project venv directly (no board lock involved — this touches only data/parcel_cache)
.venv/bin/python scripts/refresh_parcel_cache.py
echo "==> parcel-cache refresh done $(date)  size=$(du -sh data/parcel_cache | cut -f1)"
