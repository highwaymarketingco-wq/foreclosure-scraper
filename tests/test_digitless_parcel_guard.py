"""A parcel identifier with no digit is not a parcel identifier.

Trusting one as a merge key silently deletes properties. Measured on the live
board 2026-09-09: a PIN regex that matched the letters "pin" inside ordinary
words produced parcel_id 'ehurst' from "Pinehurst" and 'number' from
"PIN number:". Because both `Listing.dedupe_key()` and `dedupe._strong_sigs()`
keyed on the value without checking it, 122 distinct Pinehurst properties
collapsed into ONE row -- plus 'eville' (130), 'number' (247), 1,913 rows in
total -- and nothing in any log said so.

The guard lives at the point of HARM rather than in any one scraper, so it holds
for every source, present and future. A row with a rejected parcel still merges
on its address signatures: genuine duplicates are unaffected, it just can no
longer fuse strangers.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.dedupe import _strong_sigs, dedupe
from foreclosure_scraper.models import Listing, _normalize_parcel


@pytest.mark.parametrize("bogus", ["ehurst", "eville", "nacle", "ewood", "number",
                                   "ID", "id", "lot", "pin", "tail", "ecrest"])
def test_digitless_values_are_rejected(bogus):
    assert _normalize_parcel(bogus) == ""


@pytest.mark.parametrize("real,expected", [
    ("1234-56-7890", "1234567890"),
    ("9678774126", "9678774126"),
    ("R01700-001-001-000", "r01700001001"),
    ("964581393600000", "9645813936"),      # zero-padded GIS form collapses to the base PIN
])
def test_real_parcels_still_normalize(real, expected):
    assert _normalize_parcel(real) == expected


def _pinehurst(addr: str, pid: str) -> Listing:
    return Listing(source="liensnc", source_url="http://x", street_address=addr,
                   city="Pinehurst", county="Moore", state="NC", parcel_id=pid)


# The real addresses that shared pid='ehurst' on the board.
_REAL_ADDRESSES = [
    "80 Carolina Vista", "40 Horse Creek Run", "2145 Midland Rd", "11 BEDFORD CIR",
    "1032 Forest Creek", "7 Kilbride Dr", "225 Everette Rd", "15 Pine Vista Dr",
]


def test_bogus_parcel_no_longer_fuses_distinct_properties():
    rows = [_pinehurst(a, "ehurst") for a in _REAL_ADDRESSES]
    assert len(dedupe(rows)) == len(_REAL_ADDRESSES)


def test_bogus_parcel_emits_no_merge_signature():
    assert _strong_sigs(_pinehurst("80 Carolina Vista", "ehurst")) == set()


def test_genuine_duplicates_of_one_property_still_merge():
    rows = [
        Listing(source=f"src{i}", source_url="http://x", street_address="80 Carolina Vista",
                city="Pinehurst", county="Moore", state="NC", parcel_id="20240001")
        for i in range(6)
    ]
    assert len(dedupe(rows)) == 1


def test_county_spelling_variants_of_one_property_still_merge():
    """The board carries McDowell/Mcdowell and Rutherford/Rutherfordton variants for
    the same parcel. Those SHOULD collapse -- the guard must not block them."""
    rows = [
        Listing(source="counties_nc.rutherford_tax", source_url="http://x",
                street_address="135 GRACE ST", city="Rutherfordton",
                county="Rutherford", state="NC", parcel_id="1201147"),
        Listing(source="counties_generic.liensnc", source_url="http://x",
                street_address="135 GRACE ST", city="Rutherfordton",
                county="Rutherfordton", state="NC", parcel_id="1201147"),
    ]
    assert len(dedupe(rows)) == 1
