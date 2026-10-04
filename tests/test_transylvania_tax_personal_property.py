"""counties_nc.transylvania_delinquent_tax — Personal Property row filter (2026-10-03).

The "UnpaidBillsOnly" grid mixes real-estate and personal-property (vehicle/
boat/business-personal-property) bills with no source-type column to tell
them apart by index -- the only tell is the description cell (cell[4])
literally reading "Personal Property" instead of a parcel/map/acreage block.

Live-verified 2026-10-03: 188 of 429 current Transylvania unpaid bills (44%)
are Personal Property. The old code had no guard at all: since these bills
carry no real parcel (ViewTaxBill's "Parcel Number :" line is absent), the
grid's own literal description text "Personal Property" fell through as the
published parcel_id -- i.e. nearly half of this source's leads were fake
"properties" that are actually a delinquent vehicle/boat tax bill, not real
estate.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc.transylvania_delinquent_tax import (
    _is_personal_property,
)


def test_personal_property_description_is_detected():
    assert _is_personal_property("Personal Property<br /><br />") is True
    assert _is_personal_property("Personal Property 323 Kemp Rd NC 28768") is True
    assert _is_personal_property("personal property") is True  # case-insensitive


def test_real_estate_description_is_not_flagged():
    assert _is_personal_property(
        "8583012326000<br/>T361A01019    04 MS.03<br /><br />1.000 LT"
    ) is False
    assert _is_personal_property(None) is False
    assert _is_personal_property("") is False


def test_owner_name_mentioning_personal_is_not_flagged():
    """The match must anchor at the START of the description, not match any
    row whose OWNER or legal description happens to contain the word."""
    assert _is_personal_property("B I COTTON MILLS LO176 SE2 PL6-59") is False
