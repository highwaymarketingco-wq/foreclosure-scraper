"""SC FLC (counties_sc.sc_flc) — the buy-direct lane that had gone to 0 rows.

The old scraper scanned county treasurer LANDING PAGES for .pdf anchors. Live
probe 2026-08-02: none of the seven counties link an FLC list there any more, so
the source could only return 0 — and even on a hit it emitted one row per PDF
LINK, never a parcel. The rebuild parses the documents themselves, with an OCR
lane for the scanned lists (Anderson).

These tests pin the parsing contract; the live fetch is smoked separately.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreclosure_scraper.scrapers.counties_sc.sc_flc import (
    PARCEL_RE,
    _money,
    _normalize_ocr_row,
    _parse_text_rows,
    _wanted_doc,
)

FIXTURES = Path(__file__).parent / "fixtures"


# --- TMS recognition --------------------------------------------------------

@pytest.mark.parametrize("tms", [
    "6-18-07-092.00",       # Spartanburg
    "126-05-17-005",        # Anderson
    "072-02-01-008",        # Anderson, leading zero
    "0123-45-67-890.000",   # long dotted form
])
def test_parcel_re_matches_real_sc_tms(tms):
    assert PARCEL_RE.search(tms), f"{tms} should be recognised as an SC TMS"


@pytest.mark.parametrize("not_tms", [
    "864-596-2597",         # county phone number
    "Monday-Friday",
    "2025",
])
def test_parcel_re_rejects_non_tms(not_tms):
    assert not PARCEL_RE.search(not_tms)


# --- text-layer lane --------------------------------------------------------

def test_parse_text_rows_pulls_parcels():
    text = (
        "2025 TAX SALE PROPERTIES (REAL ESTATE) AVAILABLE FOR ASSIGNMENT\n"
        "DESCRIPTION DEFAULTING TAXPAYER MAP NUMBER TOTAL TAX DUE\n"
        "04995 1575 FARLEY AVE. EXT. KALU, ORJI UZOR 6-18-07-092.00 $ 129,306.22\n"
        "05715 S. GRIFFIN MILL CT. MARCLAR INVESTMENT, LLC 7-09-00-018.20 $ 2,047.41\n"
    )
    rows = _parse_text_rows(text)
    assert len(rows) == 2
    assert rows[0]["parcel_id"] == "6-18-07-092.00"
    assert rows[0]["amount"] == pytest.approx(129306.22)
    assert "FARLEY" in rows[0]["line"]


def test_parse_text_rows_drops_nav_chrome():
    """The 2026-06-25 junk filter must survive the rebuild: an office-address or
    footer line must not become a parcel even if it carries TMS-ish digits."""
    text = (
        "Contact the Treasurer's Office at 110 Railroad Avenue 6-18-07-092.00\n"
        "© 2021 Pickens County 6-18-07-093.00\n"
        "E-911 Addressing 6-18-07-094.00\n"
    )
    assert _parse_text_rows(text) == []


# --- OCR lane ---------------------------------------------------------------

def test_normalize_ocr_row_splits_city_out_of_address():
    row = _normalize_ocr_row({
        "item": "2745",
        "parcel_id": "072-02-01-008",
        "owner_name": "LOPEZ",
        "address": "790 Mountain View Drive in Anderson",
        "city": "",
        "amount": "1,281.65",
    })
    assert row["parcel_id"] == "072-02-01-008"
    assert row["address"] == "790 Mountain View Drive"
    assert row["city"] == "Anderson"
    assert row["owner_name"] == "LOPEZ"
    assert row["amount"] == pytest.approx(1281.65)


def test_normalize_ocr_row_rejects_rows_without_a_tms():
    """A hallucinated or header row with no tax map number must be dropped —
    address-only rows were exactly the junk the old scraper emitted."""
    assert _normalize_ocr_row({"address": "300 Hill Street", "parcel_id": ""}) is None
    assert _normalize_ocr_row({"parcel_id": "TAX MAP #"}) is None


def test_ocr_fixture_yields_only_tms_rows():
    raw = json.loads((FIXTURES / "sc_flc_anderson_ocr_rows.json").read_text())
    rows = [r for r in (_normalize_ocr_row(x) for x in raw) if r]
    assert rows, "fixture should normalise to real parcels"
    assert len(rows) < len(raw), "fixture should include at least one junk row"
    for row in rows:
        assert PARCEL_RE.fullmatch(row["parcel_id"])
        assert row["amount"] is None or row["amount"] > 0


# --- document-link classifier ----------------------------------------------

def test_wanted_doc_accepts_flc_lists():
    assert _wanted_doc("2025 Forfeited Land Commission List", "/2025REFLC.pdf")
    assert _wanted_doc("Tax Sale Assignment Listing", "/x.pdf")


def test_wanted_doc_ignores_unrelated_county_pdfs():
    """Live Anderson treasurer page links these; a naive 'fla' substring test
    used to be one filename away from harvesting them."""
    assert not _wanted_doc("County Holidays", "/2026-Holiday-Schedule.pdf")
    assert not _wanted_doc("Find a Job", "/EmploymentApplicationAndersonRev7.2026.pdf")
    assert not _wanted_doc("2026-27 ATAX Application Package",
                           "/ATAX-Application-Package-26-27-fillable.pdf")


def test_wanted_doc_rejects_bidder_and_procedure_sheets():
    """Live Cherokee/Spartanburg pages link bidder-info and policy PDFs; those
    are not inventory and must never become listings."""
    assert not _wanted_doc("Tax Sale Bidders", "/2025-BIDDER-WEBSITE-INFO-1.pdf")
    assert not _wanted_doc("Tax Sale Results", "/results.pdf")
    assert not _wanted_doc("Tax Collection and Tax Sale Procedures", "/proc.pdf")
    assert not _wanted_doc("Web Policy", "/web-policy.pdf")


def test_money_handles_both_dollar_and_bare_amounts():
    assert _money("$ 129,306.22") == pytest.approx(129306.22)
    assert _money("1,281.65") == pytest.approx(1281.65)   # OCR drops the $
    assert _money("no digits here") is None
    assert _money("$0.00") is None
