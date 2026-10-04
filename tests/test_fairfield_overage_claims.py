"""Tests for Fairfield County SC Overage Claim List PDF parser."""
from datetime import datetime

from foreclosure_scraper.main import DATELESS_OK_SOURCES, _active_only
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.scrapers.counties_sc.fairfield_overage_claims import (
    parse_overage_text,
)


def test_slug_is_dateless_whitelisted():
    """Overage claims never set sale_date (a standing unclaimed-funds
    condition, not a scheduled event) -- without this entry _active_only
    silently drops every row, the exact bug class test_dateless_ok_sources.py
    guards against for other sources."""
    assert "counties_sc.fairfield_overage_claims" in DATELESS_OK_SOURCES


def test_dateless_row_survives_active_only():
    li = Listing(
        source="counties_sc.fairfield_overage_claims",
        source_url=("https://www.fairfieldsc.com/uploads/uploads/"
                     "Tax_Sale_Overage_List___Public_Records_Notice.pdf"),
        listing_type=ListingType.TAX_SALE_OVERAGE,
        state="SC",
        county="Fairfield",
        parcel_id="170-00-00-058-000",
        owner_name="ADAMS, JAMES",
        sale_date=None,
        raw={},
    )
    assert _active_only(li, horizon_days=120, now=datetime(2026, 10, 4)) is True


# Verbatim excerpt from the live PDF (pypdf-extracted text, fetched
# 2026-10-04 from fairfieldsc.com's "Tax Sale Overage List & Public Records
# Notice"). Spans a "Tax Sale" header, the repeated column-header line, and
# one row with a space after the dollar sign ("$ 994.80") -- all real
# artifacts of this exact document, not constructed for the test.
SAMPLE_TEXT = """Tax Sale 11-1-2021
Owners Name on record at time of Tax Sale MAP# OVERAGE AMT
ADAMS, JAMES  170-00-00-058-000 $17.51
LUCAS, CHANTZ & MELISSA BROWN 169-00-01-021-000 $97.85
YOUNG, HECK JR ETAL 098-00-00-022-000 $17.07

Tax Sale 11-7-2022
Owners Name on record at time of Tax Sale MAP# OVERAGE AMT
BELTON, ESAU JR  171-00-05-010-000 $16.26
CROCKETT, LAWRENCE F  002-00-00-053-000 $ 994.80
EDWARDS, CORDIA M ETAL  177-00-00-010-000 $55,253.52
TAX SALE OVERAGE CLAIM LISTING

According To State Law, the OWNER OF RECORD IMMEDIATELY BEFORE
THE END OF REDEMPTION PERIOD OF THE TAX SALE is the legal
claimant of this overage.

HUDSON, JOHN D  170-00-00-068-000 $16.06
"""


def test_parses_standard_rows():
    records = parse_overage_text(SAMPLE_TEXT)
    names = {r["name"] for r in records}
    assert "ADAMS, JAMES" in names
    assert "LUCAS, CHANTZ & MELISSA BROWN" in names


def test_extracts_map_and_amount():
    records = parse_overage_text(SAMPLE_TEXT)
    by_name = {r["name"]: r for r in records}
    rec = by_name["ADAMS, JAMES"]
    assert rec["map_number"] == "170-00-00-058-000"
    assert rec["amount"] == 17.51


def test_tags_current_sale_date_per_record():
    records = parse_overage_text(SAMPLE_TEXT)
    by_name = {r["name"]: r for r in records}
    assert by_name["ADAMS, JAMES"]["tax_sale_date"] == "11-1-2021"
    assert by_name["BELTON, ESAU JR"]["tax_sale_date"] == "11-7-2022"
    # a record on the far side of a simulated page break (no new "Tax Sale"
    # header before it) must still carry the LAST header it saw.
    assert by_name["HUDSON, JOHN D"]["tax_sale_date"] == "11-7-2022"


def test_amount_with_space_after_dollar_sign():
    records = parse_overage_text(SAMPLE_TEXT)
    by_name = {r["name"]: r for r in records}
    assert by_name["CROCKETT, LAWRENCE F"]["amount"] == 994.80


def test_handles_large_comma_amount():
    records = parse_overage_text(SAMPLE_TEXT)
    by_name = {r["name"]: r for r in records}
    assert by_name["EDWARDS, CORDIA M ETAL"]["amount"] == 55253.52


def test_skips_column_header_and_boilerplate_lines():
    records = parse_overage_text(SAMPLE_TEXT)
    names = {r["name"] for r in records}
    assert not any("OVERAGE AMT" in n.upper() for n in names)
    assert not any("ACCORDING TO STATE LAW" in n.upper() for n in names)
    assert not any("TAX SALE OVERAGE CLAIM LISTING" in n.upper() for n in names)


def test_blank_lines_do_not_break_parsing():
    records = parse_overage_text(SAMPLE_TEXT)
    names = {r["name"] for r in records}
    assert "HUDSON, JOHN D" in names


def test_empty_text():
    assert parse_overage_text("") == []
    assert parse_overage_text("no data here\njust some text") == []
