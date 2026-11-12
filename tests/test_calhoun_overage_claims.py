"""Tests for Calhoun County SC Overage Claim List parsers (3 yearly PDFs)."""
from datetime import datetime

from foreclosure_scraper.main import DATELESS_OK_SOURCES, _active_only
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.scrapers.counties_sc.calhoun_overage_claims import (
    parse_overage_text,
)


def test_slug_is_dateless_whitelisted():
    """Overage claims never set sale_date (a standing unclaimed-funds
    condition, not a scheduled event) -- without this entry _active_only
    silently drops every row, the exact bug class test_dateless_ok_sources.py
    guards against for other sources."""
    assert "counties_sc.calhoun_overage_claims" in DATELESS_OK_SOURCES


def test_dateless_row_survives_active_only():
    li = Listing(
        source="counties_sc.calhoun_overage_claims",
        source_url=("https://calhouncounty.sc.gov/sites/calhouncounty/files/Documents/"
                     "Calhoun%20County/Departments/Tax%20Collector/Overages/"
                     "CALHOUN-TaxColOvr_2021.pdf"),
        listing_type=ListingType.TAX_SALE_OVERAGE,
        state="SC",
        county="Calhoun",
        parcel_id="074-00-02-018",
        owner_name="Almonds, Romeo Jr.",
        sale_date=None,
        raw={},
    )
    assert _active_only(li, horizon_days=120, now=datetime(2026, 10, 4)) is True


# Verbatim excerpt from the live 2021 list PDF (pypdf-extracted text,
# fetched 2026-10-04 from CALHOUN-TaxColOvr_2021.pdf). Real artifacts of
# THIS document, not constructed for the test: a Unicode hyphen (‐) in every
# map number, the dollar amount printed BEFORE its "$" with trailing spaces
# ("736.47 $        "), and one row ("Heirs of Judy Hopkins...") whose map
# number has a stray space baked into its own text layer ("079‐00‐03‐0 10").
SAMPLE_2021 = (
    "Sale Number Taxpayer Map Number Overage\n"
    "202100004 Almonds, Romeo Jr. 074‐00‐02‐018 736.47 $        \n"
    "202100034 Brown, Linda Marie 069‐00‐01‐018.02 155.04 $        \n"
    "202100228 Heirs of Judy Hopkins & Milton Hopkins ETAL 079‐00‐03‐0 10 3,891.37$    \n"
)

# Verbatim excerpt from the live 2022 list PDF (plain ASCII, normal
# "$123.45" ordering -- fetched 2026-10-04 from CALHOUN-TaxColOvr_2022.pdf).
SAMPLE_2022 = (
    "Sale# Taxpayer Map# Overage\n"
    "202200002 Adams, Robert Jr. 167-00-00-035 $763.10\n"
    "202200161 Gerald, Elizabeth H. and Heather A. Smith 037-00-00-018.02 $203.46\n"
)

# Verbatim excerpt from the live 2023 list PDF -- this year's document adds
# a "TAX SALE DATE:" header line the 2021/2022 PDFs don't have, and prints
# "$" with a variable run of internal spaces before the digits.
SAMPLE_2023 = (
    "TAX SALE DATE: NOVEMBER 13, 2023 \n"
    "Sale#  Taxpayer Map#  Overage  \n"
    "202300005  Adams, Robert Jr. 167-00-00-039  $        982.02  \n"
)


def test_parses_2021_reversed_dollar_sign_rows():
    records = parse_overage_text(SAMPLE_2021, "2021")
    by_sale = {r["sale_number"]: r for r in records}
    rec = by_sale["202100004"]
    assert rec["name"] == "Almonds, Romeo Jr."
    assert rec["map_number"] == "074-00-02-018"
    assert rec["amount"] == 736.47


def test_decimal_suffix_map_number_not_mistaken_for_amount():
    records = parse_overage_text(SAMPLE_2021, "2021")
    by_sale = {r["sale_number"]: r for r in records}
    rec = by_sale["202100034"]
    assert rec["map_number"] == "069-00-01-018.02"
    assert rec["amount"] == 155.04


def test_embedded_space_glitch_recovers_full_map_number_and_amount():
    """Regression: the final TMS segment's own text-layer artifact
    ('0 10' for '010') must not swallow the first digits of the dollar
    amount that follows it on the same line."""
    records = parse_overage_text(SAMPLE_2021, "2021")
    by_sale = {r["sale_number"]: r for r in records}
    rec = by_sale["202100228"]
    assert rec["map_number"] == "079-00-03-010"
    assert rec["amount"] == 3891.37
    assert rec["name"] == "Heirs of Judy Hopkins & Milton Hopkins ETAL"


def test_normal_three_digit_final_segment_not_corrupted_by_embedded_space_guard():
    """Regression for the bug the fix above could reintroduce: a normal,
    un-glitched row whose map number's last segment is followed by a
    dollar amount beginning with 1-2 digits must NOT have those digits
    stolen into the map number (the original bug produced map_number
    '074-00-02-01873' / amount '$6.47' instead of '074-00-02-018' /
    '$736.47' for this exact row before the lookahead guard was added)."""
    records = parse_overage_text(SAMPLE_2021, "2021")
    by_sale = {r["sale_number"]: r for r in records}
    rec = by_sale["202100004"]
    assert rec["map_number"] == "074-00-02-018"
    assert rec["amount"] == 736.47


def test_parses_2022_plain_ascii_rows():
    records = parse_overage_text(SAMPLE_2022, "2022")
    by_sale = {r["sale_number"]: r for r in records}
    rec = by_sale["202200002"]
    assert rec["name"] == "Adams, Robert Jr."
    assert rec["map_number"] == "167-00-00-035"
    assert rec["amount"] == 763.10


def test_default_year_used_when_no_tax_sale_date_header():
    records = parse_overage_text(SAMPLE_2021, "2021")
    assert all(r["tax_sale_date"] == "2021" for r in records)
    records = parse_overage_text(SAMPLE_2022, "2022")
    assert all(r["tax_sale_date"] == "2022" for r in records)


def test_explicit_tax_sale_date_header_overrides_default_year():
    records = parse_overage_text(SAMPLE_2023, "2023")
    by_sale = {r["sale_number"]: r for r in records}
    assert by_sale["202300005"]["tax_sale_date"] == "NOVEMBER 13, 2023"
    assert by_sale["202300005"]["amount"] == 982.02
    assert by_sale["202300005"]["map_number"] == "167-00-00-039"


def test_skips_header_line():
    for records in (
        parse_overage_text(SAMPLE_2021, "2021"),
        parse_overage_text(SAMPLE_2022, "2022"),
        parse_overage_text(SAMPLE_2023, "2023"),
    ):
        for r in records:
            assert r["name"].upper() not in ("TAXPAYER", "SALE NUMBER TAXPAYER MAP NUMBER OVERAGE")


def test_empty_text():
    assert parse_overage_text("", "2021") == []
    assert parse_overage_text("no data here\njust some text", "2021") == []
