#!/usr/bin/env python3
"""Test dedup match for a real liensnc row shape."""
import sys
sys.path.insert(0, "src")

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import _append_row_sigs, _append_dict_sigs
from foreclosure_scraper.dedupe import _strong_sigs
from foreclosure_scraper.verification.core import row_keys

# Real liensnc row shape from walled output
row_dict = {
    "source": "counties_generic.liensnc",
    "source_url": "https://apps.liensnc.com/scr/appointment/details.html?entryNumber=2693096&printable=",
    "listing_type": "tax_lien",
    "street_address": "5244 Ruth Dr",
    "city": None,
    "state": "NC",
    "zip_code": None,
    "county": "Mecklenburg",
    "parcel_id": None,
    "case_number": "2693096",
    "plaintiff": None,
    "defendant": "@Francis",
    "trustee": None,
    "sale_date": None,
    "sale_time": None,
    "sale_location": None,
    "opening_bid": None,
    "judgment_amount": None,
    "legal_description": None,
}

li = Listing(
    source="counties_generic.liensnc",
    source_url="https://apps.liensnc.com/scr/appointment/details.html?entryNumber=2693096&printable=",
    listing_type=ListingType.TAX_LIEN,
    street_address="5244 Ruth Dr",
    state="NC",
    county="Mecklenburg",
    case_number="2693096",
    defendant="@Francis",
    raw={},
)

print("=== _strong_sigs (old system) ===")
print(_strong_sigs(li))
print()
print("=== row_keys() (wire script system) ===")
print(row_keys(li))
print()
print("=== _append_row_sigs (NEW, includes both) ===")
sigs = _append_row_sigs(li)
print(sigs)
print()
print("=== _append_dict_sigs (for board dict) ===")
dict_sigs = _append_dict_sigs(row_dict)
print(dict_sigs)
print()
print(f"Match between Listing sigs and dict sigs: {bool(sigs & dict_sigs)}")
