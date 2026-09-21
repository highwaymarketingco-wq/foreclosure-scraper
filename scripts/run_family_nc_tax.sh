#!/bin/zsh
# NC county delinquent-tax pulls: Rutherford, PTS Cloud, county PDFs and CSVs, Buncombe, Transylvania.
# Scheduled by deploy/mac/com.highway.foreclosure.family-nc_tax.plist. See scripts/family_common.sh
# for the three phases, and scripts/family_merge.py for what the merge does.
export FAMILY_SCRAPE_TIMEOUT="${FAMILY_SCRAPE_TIMEOUT:-5400}"
export FAMILY_MERGE_TIMEOUT="${FAMILY_MERGE_TIMEOUT:-5400}"
. "${FORECLOSURE_ROOT:-$HOME/foreclosure-scraper}/scripts/family_common.sh"
family_job nc_tax
exit $?
