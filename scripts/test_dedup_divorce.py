#!/usr/bin/env python3
"""Test the hardest case: truly identity-less rows where only names differ."""
import sys
sys.path.insert(0, "src")

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import _append_row_sigs, _append_dict_sigs
from foreclosure_scraper.verification.core import row_keys

# Divorce row - has case_number but no address/parcel
board_row = {
    "source": "counties_nc.nc_ecourts_divorce",
    "source_url": "https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/#/search?caseNumber=26CV002520-480",
    "listing_type": "divorce_notice",
    "street_address": None,
    "city": None,
    "state": "NC",
    "zip_code": None,
    "county": "Iredell",
    "parcel_id": None,
    "case_number": "26CV002520-480",
    "plaintiff": "Anderson, Kari",
    "defendant": "Anderson, Mark",
    "trustee": None,
    "sale_date": None,
    "sale_time": None,
    "sale_location": None,
    "opening_bid": None,
    "judgment_amount": None,
    "legal_description": None,
}

# Same row coming through walled output (same source_url because model_dump preserves it)
walled_li = Listing(
    source="counties_nc.nc_ecourts_divorce",
    source_url="https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/#/search?caseNumber=26CV002520-480",
    listing_type=ListingType.DIVORCE_NOTICE,
    street_address=None,
    state="NC",
    county="Iredell",
    case_number="26CV002520-480",
    plaintiff="Anderson, Kari",
    defendant="Anderson, Mark",
    raw={},
)

board_sigs = _append_dict_sigs(board_row)
walled_sigs = _append_row_sigs(walled_li)
overlap = board_sigs & walled_sigs

print(f"Board sigs: {board_sigs}")
print()
print(f"Walled sigs: {walled_sigs}")
print()
print(f"Overlap: {overlap}")
print()
print(f"MATCH: {bool(overlap)}")
