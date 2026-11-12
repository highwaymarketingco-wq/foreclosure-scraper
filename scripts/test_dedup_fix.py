#!/usr/bin/env python3
"""Test that the dedup fix catches identity-less rows."""
import sys
sys.path.insert(0, "src")

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import _append_row_sigs, _append_dict_sigs

# TRULY identity-less row (no parcel, no address, no case_number)
board_row = {
    "source": "judgment_liens",
    "source_url": "https://www3.ncdor.gov/jl_search.jsp",
    "listing_type": "lien_claim",
    "street_address": None,
    "city": None,
    "state": "NC",
    "zip_code": None,
    "county": "lincoln",
    "parcel_id": None,
    "case_number": None,
    "plaintiff": "Bank of America",
    "defendant": "John Smith",
    "trustee": None,
    "sale_date": None,
    "sale_time": None,
    "sale_location": None,
    "opening_bid": None,
    "judgment_amount": 30000,
    "legal_description": None,
}

# Same row through walled_output with different source_url
walled_li = Listing(
    source="judgment_liens",
    source_url="walled://judgment_liens",
    listing_type=ListingType.LIEN_CLAIM,
    street_address=None,
    state="NC",
    county="lincoln",
    case_number=None,
    plaintiff="Bank of America",
    defendant="John Smith",
    judgment_amount=30000,
    raw={},
)

board_sigs = _append_dict_sigs(board_row)
walled_sigs = _append_row_sigs(walled_li)

overlap = board_sigs & walled_sigs
print(f"Board sigs ({len(board_sigs)}): {board_sigs}")
print()
print(f"Walled sigs ({len(walled_sigs)}): {walled_sigs}")
print()
print(f"Overlap ({len(overlap)}): {overlap}")
print()
print(f"WOULD DEDUPE CATCH THIS: {bool(overlap)}")
print()
print("Before fix: board_sigs had ('k','url:https://...') and walled_sigs had ('k','url:walled://...') -- NO MATCH")
