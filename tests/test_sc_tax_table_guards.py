"""The shared SC tax-table guards, and proof every copy of the parser uses them.

Six SC county scrapers carry a copy-pasted hand-rolled table parser (darlington,
fairfield, york, saluda, lancaster, newberry). They shared one defect: a county
treasurer page's OFFICE-HOURS table is also a <table> of <tr>, and it passed both of
their filters -- "Monday" was not in the header skip list, and "8:30 a.m. - 5:00 p.m."
satisfied the digit test -- while `parcel` was allowed to be None and the row emitted
anyway. Fed a populated hours table they produced
`defendant='Monday' street_address='8:30 a.m. - 5:00 p.m.'` as a TAX_SALE lead.

`_active_only()` in main.py had been absorbing this by accident: it deletes rows with
no sale_date, and these rows have none. Adding these slugs to DATELESS_OK_SOURCES was
correct on its own terms but removed that unintended backstop. A pipeline filter is
not a data-quality guard.

The last test is the one that matters long-term: it asserts every copy of the parser
actually routes through the shared gate, so the seventh copy cannot quietly reintroduce
the bug.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from foreclosure_scraper.scrapers.counties_sc._sc_tax_table import (
    find_tms,
    is_label_row,
    is_usable_row,
)

_SC_DIR = (Path(__file__).resolve().parent.parent
           / "src" / "foreclosure_scraper" / "scrapers" / "counties_sc")

#: Every module carrying the copy-pasted parser.
GUARDED_PARSERS = [
    "darlington_delinquent_tax",
    "fairfield_delinquent_tax",
    "york_delinquent_tax",
    "saluda_delinquent_tax",
    "lancaster_delinquent_tax",
    "newberry_delinquent_tax",
]


@pytest.mark.parametrize("cells", [
    ["Monday", "8:30 a.m. - 5:00 p.m."],
    ["Tuesday", "8:30 a.m. - 5:00 p.m."],
    ["Saturday", "Closed 24/7 843-398-4170"],
    ["Days", "Hours"],
    ["", "Monday", "9:00"],              # blank leading cell -- slipped the old 2-cell test
])
def test_office_hours_rows_are_never_usable(cells):
    assert is_usable_row(cells, find_tms(cells)) is False


@pytest.mark.parametrize("cells", [
    ["Owner", "TMS", "Address"],
    ["Name", "Parcel", "Amount Due"],
    ["#", "Map", "Total"],
])
def test_header_rows_are_never_usable(cells):
    assert is_label_row(cells) is True
    assert is_usable_row(cells, find_tms(cells)) is False


@pytest.mark.parametrize("cells,tms", [
    (["SMITH JOHN", "123-45-67-890", "101 Main St"], "123-45-67-890"),
    (["JONES MARY", "1234 56 78 901", "202 Oak Ave"], "1234 56 78 901"),
    (["BROWN W", "1234567890123", "303 Pine"], "1234567890123"),
])
def test_real_tax_sale_rows_survive(cells, tms):
    assert find_tms(cells) == tms
    assert is_usable_row(cells, tms) is True


def test_a_row_with_no_tms_is_rejected():
    """No parcel means the lead cannot be underwritten, joined or routed."""
    cells = ["SMITH JOHN", "101 Main St"]
    assert find_tms(cells) is None
    assert is_usable_row(cells, None) is False


def test_a_phone_number_is_not_mistaken_for_a_parcel():
    """8435551234 is 10 digits and would satisfy the bare-parcel pattern, so the
    schedule labels have to catch the row before find_tms is trusted."""
    cells = ["Saturday", "Closed 8435551234"]
    assert is_usable_row(cells, find_tms(cells)) is False


@pytest.mark.parametrize("module", GUARDED_PARSERS)
def test_every_copy_of_the_parser_routes_through_the_shared_gate(module):
    """THE load-bearing test. Six copies of one parser exist; if a seventh is made,
    or one is edited to drop the gate, this fails instead of silently regressing."""
    src = (_SC_DIR / f"{module}.py").read_text()
    assert "Listing(" in src, f"{module} no longer builds Listings -- update this test"
    guarded = ("_sc_tax_table" in src) or ("if not parcel" in src)
    assert guarded, (
        f"{module} builds Listings without the shared junk-row gate. Import "
        f"is_usable_row from ._sc_tax_table and gate the append, or the office-hours "
        f"table can become tax-sale leads again."
    )
