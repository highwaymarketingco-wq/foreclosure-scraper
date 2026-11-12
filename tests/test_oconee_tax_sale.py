"""Oconee SC delinquent-tax CSV parser.

The published Google Sheet holds announcement placeholder rows between sale
cycles; only rows with BOTH an Item Number and a Map (TMS) Number are real
listings. Locks in placeholder-skipping + field mapping so the source works
the moment the county posts the November sale list.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.main import DATELESS_OK_SOURCES
from foreclosure_scraper.scrapers.counties_sc.oconee_tax_sale import (
    _parse_csv,
    _parse_sale_date,
)

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


def test_parses_sale_date_from_announcement_text():
    # The county's own placeholder row states the one auction date that
    # applies to every real row on the list (verified live 2026-10-01: "The
    # 2026 Tax Sale is scheduled for Monday, November 9, 2026.").
    assert _parse_sale_date(
        "The 2026 Tax Sale is scheduled for Monday, November 9, 2026."
    ) == datetime(2026, 11, 9)
    assert _parse_sale_date("Bidder registration opens Oct 29.") is None


def test_real_rows_get_the_announced_sale_date_stamped():
    csv_text = (
        HEADER
        + ',"The 2026 Tax Sale is scheduled for Monday, November 9, 2026.",,,\n'
        + '1,SMITH JOHN,"123-45-67-890","1.5 AC LOT 4","$1,234.56"\n'
    )
    out = _parse_csv(csv_text)
    assert len(out) == 1
    a = out[0]
    assert a.sale_date == datetime(2026, 11, 9)
    assert a.raw["oconee_tax_sale"]["sale_date"] == "2026-11-09"


def test_real_rows_without_a_parseable_announcement_still_fall_back_safely():
    # If the sheet's wording ever changes and the date can't be parsed, rows
    # still emit (sale_date=None) -- this is exactly why the slug is also
    # kept in DATELESS_OK_SOURCES as a backstop so the horizon filter does
    # not silently delete them.
    csv_text = HEADER + '1,SMITH JOHN,"123-45-67-890","1.5 AC LOT 4","$1,234.56"\n'
    out = _parse_csv(csv_text)
    assert len(out) == 1
    assert out[0].sale_date is None


def test_dateless_ok_sources_backstop_is_registered():
    assert "counties_sc.oconee_tax_sale" in DATELESS_OK_SOURCES
