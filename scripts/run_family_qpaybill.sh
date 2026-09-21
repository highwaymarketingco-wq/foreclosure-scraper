#!/bin/zsh
# qPayBill SC delinquent-tax roll (33,528 board rows) + balance fill. Scrape is the slow part (27 county portals): capped at 5 h, off the lock.
# Scheduled by deploy/mac/com.highway.foreclosure.family-qpaybill.plist. See scripts/family_common.sh
# for the three phases, and scripts/family_merge.py for what the merge does.
export FAMILY_SCRAPE_TIMEOUT="${FAMILY_SCRAPE_TIMEOUT:-18000}"
export FAMILY_MERGE_TIMEOUT="${FAMILY_MERGE_TIMEOUT:-5400}"
export FAMILY_POST=1
. "${FORECLOSURE_ROOT:-$HOME/foreclosure-scraper}/scripts/family_common.sh"
family_job qpaybill
exit $?
