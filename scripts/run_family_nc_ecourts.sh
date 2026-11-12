#!/bin/zsh
# NC eCourts open Judgment Search: lis pendens and liens (3,273 board rows), stored dateless.
# Scheduled by deploy/mac/com.highway.foreclosure.family-nc_ecourts.plist. See scripts/family_common.sh
# for the three phases, and scripts/family_merge.py for what the merge does.
export FAMILY_SCRAPE_TIMEOUT="${FAMILY_SCRAPE_TIMEOUT:-2400}"
export FAMILY_MERGE_TIMEOUT="${FAMILY_MERGE_TIMEOUT:-3600}"
. "${FORECLOSURE_ROOT:-$HOME/foreclosure-scraper}/scripts/family_common.sh"
family_job nc_ecourts
exit $?
