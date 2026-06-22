"""Oconee SC delinquent-tax CSV parser.

The published Google Sheet holds announcement placeholder rows between sale
cycles; only rows with BOTH an Item Number and a Map (TMS) Number are real
listings. Locks in placeholder-skipping + field mapping so the source works
the moment the county posts the November sale list.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc.oconee_tax_sale import _parse_csv

HEADER = "Item Number,Owner Name,Map Number,Description,Total Tax Due\n"


def test_skips_placeholder_announcement_rows():
    csv_text = HEADER + ",The 2026 Tax Sale is scheduled for Monday November 9 2026.,,,\n"
    assert _parse_csv(csv_text) == []


def test_parses_real_rows():
    csv_text = (
        HEADER
        + ",Bidder registration opens Oct 29.,,,\n"  # placeholder, skipped
        + '1,SMITH JOHN,"123-45-67-890","1.5 AC LOT 4","$1,234.56"\n'
        + '2,DOE JANE,"500-07-02-004","HOUSE & LOT","845.00"\n'
    )
    out = _parse_csv(csv_text)
    assert len(out) == 2
    a = out[0]
    assert a.state == "SC" and a.county == "Oconee"
    assert a.parcel_id == "123-45-67-890"
    assert a.defendant == "SMITH JOHN"
    assert a.judgment_amount == 1234.56
    assert a.listing_type.value == "tax_sale"


def test_row_missing_map_number_is_skipped():
    # An item number without a TMS isn't an actionable parcel.
    csv_text = HEADER + '9,SOME OWNER,,"no map",100.00\n'
    assert _parse_csv(csv_text) == []
