"""Spartanburg County SC Forfeited Land Commission — assignable tax-sale surplus PDF.

Audited 2026-10-01. The live PDF (5 current rows) exposed two real bugs in
the owner/address split, both fixed here:

1. A situs with no leading house number (e.g. "S. GRIFFIN MILL CT.",
   "W.O. EZELL BLVD" — both real, live rows) was unconditionally nulled out
   by a `re.match(r"^\\d", address)` guard, even though the owner-comma split
   had already cleanly separated it from the owner text. 2 of 5 live rows
   lost their only address field for no reason.

2. A multi-word company owner name ("MARCLAR INVESTMENT, LLC", "WK PEBBLES,
   LLC") only had its LAST word captured by the single-word-before-the-comma
   _OWNER regex, leaving the first word(s) stuck onto the address
   ("S. GRIFFIN MILL CT. MARCLAR", "N. CONVERST ST. WK"). Fixed by anchoring
   on the last STREET-SUFFIX token instead when one is found with a comma
   after it, which keeps the whole company name together.

Both fixes are additive to the parsing logic; parse_flc_pdf() itself needs no
network mocking since it operates on already-extracted PDF text.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from foreclosure_scraper.scrapers.counties_sc import spartanburg_flc as mod


def _fake_pdfplumber_open(lines: list[str]):
    """Build a pdfplumber.open(...) context manager stand-in yielding one
    page whose extract_text() returns the given lines joined by newlines."""
    page = MagicMock()
    page.extract_text.return_value = "\n".join(lines)
    pdf = MagicMock()
    pdf.pages = [page]
    pdf.__enter__ = MagicMock(return_value=pdf)
    pdf.__exit__ = MagicMock(return_value=False)
    return pdf


# The 5 real rows live-captured 2026-10-01 from
# https://www.spartanburgcounty.gov/DocumentCenter/View/104130
_LIVE_LINES = [
    "2025 TAX SALE PROPERTIES (REAL ESTATE) AVAILABLE FOR ASSIGNMENT",
    "DESCRIPTION DEFAULTING TAXPAYER MAP NUMBER TOTAL TAX DUE",
    "ITEM # best known property address Owner Name Bid Amount Needed",
    "05715 S. GRIFFIN MILL CT. MARCLAR INVESTMENT, LLC 7-09-00-018.20 $ 2,047.41",
    "06218 W.O. EZELL BLVD MILLER, ROOSEVELT 6-21-02-056.01 $ 1,199.38",
    "07263 1120 HAYNE ST. POPESCU, IVAN & POPESCU, TATYANA 6-13-14-121.00 $ 55,837.13",
    "08233 642 MAYWOOD ST. SIFFORD, THOMAS 7-12-03-068.00 $ 20,798.80",
    "10020 N. CONVERST ST. WK PEBBLES, LLC 7-12-06-130.00 $ 2,754.34",
]


def _parse(lines):
    with patch("pdfplumber.open", return_value=_fake_pdfplumber_open(lines)):
        return mod.parse_flc_pdf(b"%PDF-fake")


def test_all_five_live_rows_parse():
    rows = _parse(_LIVE_LINES)
    assert len(rows) == 5


def test_no_house_number_situs_is_kept_not_nulled():
    rows = _parse(_LIVE_LINES)
    by_tms = {r.parcel_id: r for r in rows}
    assert by_tms["7-09-00-018.20"].street_address == "S. GRIFFIN MILL CT."
    assert by_tms["6-21-02-056.01"].street_address == "W.O. EZELL BLVD"


def test_multiword_company_owner_name_kept_whole():
    rows = _parse(_LIVE_LINES)
    by_tms = {r.parcel_id: r for r in rows}
    assert by_tms["7-09-00-018.20"].owner_name == "MARCLAR INVESTMENT, LLC"
    assert by_tms["7-12-06-130.00"].owner_name == "WK PEBBLES, LLC"
    # ...and the company-name words are NOT left stuck onto the address.
    assert by_tms["7-09-00-018.20"].street_address == "S. GRIFFIN MILL CT."
    assert by_tms["7-12-06-130.00"].street_address == "N. CONVERST ST."


def test_plain_person_owner_rows_unaffected():
    rows = _parse(_LIVE_LINES)
    by_tms = {r.parcel_id: r for r in rows}
    assert by_tms["6-13-14-121.00"].owner_name == "POPESCU, IVAN & POPESCU, TATYANA"
    assert by_tms["6-13-14-121.00"].street_address == "1120 HAYNE ST."
    assert by_tms["7-12-03-068.00"].owner_name == "SIFFORD, THOMAS"
    assert by_tms["7-12-03-068.00"].street_address == "642 MAYWOOD ST."


def test_total_tax_due_parsed_as_opening_bid():
    rows = _parse(_LIVE_LINES)
    by_tms = {r.parcel_id: r for r in rows}
    assert by_tms["6-13-14-121.00"].opening_bid == 55837.13


def test_header_and_instruction_lines_produce_no_rows():
    rows = _parse(_LIVE_LINES)
    assert all(r.parcel_id for r in rows)
    assert len(rows) == 5  # only the 5 real item# lines, not the 8 header/instruction lines


def test_duplicate_tms_deduped():
    doubled = _LIVE_LINES + [_LIVE_LINES[-1]]
    rows = _parse(doubled)
    assert len(rows) == 5


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "counties_sc.spartanburg_flc" in {s.slug for s in all_scrapers()}
