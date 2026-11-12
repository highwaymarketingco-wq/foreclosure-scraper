"""Tests for Laurens County SC Overage Claim List (scanned-PDF OCR lane).

The fixture tests/fixtures/laurens_overage_ocr_page1.json is REAL Gemini OCR
output captured from a live run against the actual county PDF on 2026-10-04
(see laurens_overage_claims.py's module docstring) -- not a synthetic
sample. The live fetch itself (network + OCR provider) is smoked separately
via `uv run python -m foreclosure_scraper.scrapers.counties_sc.laurens_overage_claims`.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from foreclosure_scraper.main import DATELESS_OK_SOURCES, _active_only
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.scrapers.counties_sc.laurens_overage_claims import (
    TMS_RE,
    _money,
    _normalize_row,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_slug_is_dateless_whitelisted():
    assert "counties_sc.laurens_overage_claims" in DATELESS_OK_SOURCES


def test_dateless_row_survives_active_only():
    li = Listing(
        source="counties_sc.laurens_overage_claims",
        source_url="https://www.laurenscountysc.gov/departments/treasurer/forms_and_documents.php",
        listing_type=ListingType.TAX_SALE_OVERAGE,
        state="SC",
        county="Laurens",
        parcel_id="906-10-02-022",
        owner_name="ABERCROMBIE LAURA",
        sale_date=None,
        raw={},
    )
    assert _active_only(li, horizon_days=120, now=datetime(2026, 10, 4)) is True


def test_money_handles_commas_and_bare_amounts():
    assert _money("$1,422.54") == 1422.54
    assert _money("48,537.27") == 48537.27
    assert _money("5.57") == 5.57
    assert _money("") is None
    assert _money("no digits here") is None


def test_normalize_row_basic():
    rec = _normalize_row("DECEMBER 8, 2021", {
        "item": "5", "map_number": "906-10-02-022",
        "owner_name": "ABERCROMBIE LAURA", "amount": "5.57",
    })
    assert rec["map_number"] == "906-10-02-022"
    assert rec["owner_name"] == "ABERCROMBIE LAURA"
    assert rec["amount"] == 5.57
    assert rec["tax_sale_date"] == "DECEMBER 8, 2021"
    assert rec["item"] == "5"


def test_normalize_row_keeps_joined_multi_owner_string():
    """Co-owners/heirs are pre-joined by the OCR prompt into one owner_name
    (semicolon-separated) -- the normalizer must pass that through whole,
    not try to re-split it."""
    rec = _normalize_row("DECEMBER 8, 2021", {
        "item": "1412", "map_number": "906-16-04-022",
        "owner_name": "JONES, ANNIE; MOBLEY VALERIE; MOBLEY ERIC L; SIMPSON ERNEST",
        "amount": "1,443.19",
    })
    assert rec["owner_name"] == "JONES, ANNIE; MOBLEY VALERIE; MOBLEY ERIC L; SIMPSON ERNEST"
    assert rec["amount"] == 1443.19


def test_normalize_row_rejects_missing_tms():
    assert _normalize_row("2021", {"owner_name": "NO PARCEL HERE", "amount": "5.00"}) is None


def test_normalize_row_rejects_missing_owner():
    assert _normalize_row("2021", {"map_number": "906-10-02-022", "amount": "5.00"}) is None


def test_normalize_row_rejects_zero_or_blank_amount():
    assert _normalize_row("2021", {
        "map_number": "906-10-02-022", "owner_name": "SOMEONE", "amount": "0.00",
    }) is None
    assert _normalize_row("2021", {
        "map_number": "906-10-02-022", "owner_name": "SOMEONE", "amount": "",
    }) is None


def test_normalize_row_rejects_blank_row():
    assert _normalize_row("2021", {"item": "", "map_number": "", "owner_name": "", "amount": ""}) is None


def test_tms_re_matches_laurens_format():
    assert TMS_RE.search("906-10-02-022")
    assert TMS_RE.search("244-01-01-063")
    assert not TMS_RE.search("Monday-Friday")


def test_fixture_page_normalizes_to_expected_real_claims():
    """End-to-end over the captured real OCR response: the one fully-blank
    row is dropped, the multi-owner row's names stay joined, amounts parse."""
    data = json.loads((FIXTURES / "laurens_overage_ocr_page1.json").read_text())
    tax_sale_date = data["tax_sale_date"]
    records = [r for r in (_normalize_row(tax_sale_date, row) for row in data["rows"]) if r]
    assert len(records) == 4  # the 5th row (fully blank) must be dropped
    by_item = {r["item"]: r for r in records}
    assert by_item["5"]["amount"] == 5.57
    assert by_item["170"]["amount"] == 48537.27
    assert by_item["806"]["owner_name"] == "DUDLEY DERRIAL P; DUDLEY ELAINE G"
    assert by_item["1412"]["owner_name"].count(";") == 3  # four names, three separators
    for r in records:
        assert r["tax_sale_date"] == "DECEMBER 8, 2021"
