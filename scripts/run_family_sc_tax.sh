#!/bin/zsh
# SC county delinquent-tax pulls: Berkeley, Greenville, Florence, Pickens, Spartanburg, Charleston, Dillon, Cherokee.
# Scheduled by deploy/mac/com.highway.foreclosure.family-sc_tax.plist. See scripts/family_common.sh
# for the three phases, and scripts/family_merge.py for what the merge does.
export FAMILY_SCRAPE_TIMEOUT="${FAMILY_SCRAPE_TIMEOUT:-7200}"
export FAMILY_MERGE_TIMEOUT="${FAMILY_MERGE_TIMEOUT:-5400}"
. "${FORECLOSURE_ROOT:-$HOME/foreclosure-scraper}/scripts/family_common.sh"
family_job sc_tax
exit $?
