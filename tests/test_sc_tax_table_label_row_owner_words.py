"""_sc_tax_table.is_label_row: an owner name holding a label word ('owner', 'office') must not
drop a data row that has a parcel number and an amount (audit 2026-10-09). Made-up rows."""
from foreclosure_scraper.scrapers.counties_sc._sc_tax_table import is_label_row


def test_data_row_with_label_words_in_the_owner_is_kept():
    assert not is_label_row(["SAMPLE HOMEOWNERS ASSN", "123-45-67-890", "$1,234.56"])
    assert not is_label_row(["SAMPLE OFFICE PARK LLC", "0012345678", "88.10"])


def test_headers_and_office_hours_are_still_furniture():
    assert is_label_row(["Owner Name", "TMS #", "Amount Due"])
    assert is_label_row(["Monday", "8:30 a.m. - 5:00 p.m.", ""])
    assert is_label_row(["", "Office hours", "Closed"])
