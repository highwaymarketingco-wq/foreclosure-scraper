"""Tests for York County SC Overage Claim List PDF parser."""
from foreclosure_scraper.scrapers.counties_sc.york_overage_claims import parse_overage_pdf

# Verbatim excerpt from the live PDF (pypdf-extracted text, 2026-09-14),
# spanning a section boundary and a blank-line-between-records case.
SAMPLE_TEXT = """Tax Sale 11/15/2021
NAME
 MAP #
 OVERAGE AMT
ANDREWS MINERVA W ETAL
 070-09-01-017
 $15,733.32
BROOKS MAGGIE
 070-12-05-009
 $14,466.01
 Tax Sale 10/24/2022
NAME
 MAP#
 OVERAGE AMT
PRESTON RUTH W ETAL
 070-06-06-002
 $8,122.86

RAWLINSON DAVID H JR & RAWLINSON ROSALIND L
 600-07-01-013
 $510.82
UNKNOWN
 176-00-00-009
 $2,108.45
 Tax Sale 10/28/2024

NAME
 MAP#
 OVERAGE AMT
IRVIN BETTY ETAL
 080-03-01-006
 $9,404.21
LEAKE ROBERT K JR & WYNETTE S
 628-11-02-017
 $22,874.90
**UPDATED 8/11/26**
"""


def test_parses_standard_rows():
    records = parse_overage_pdf(SAMPLE_TEXT)
    names = {r["name"] for r in records}
    assert "ANDREWS MINERVA W ETAL" in names
    assert "BROOKS MAGGIE" in names


def test_extracts_map_and_amount():
    records = parse_overage_pdf(SAMPLE_TEXT)
    by_name = {r["name"]: r for r in records}
    rec = by_name["ANDREWS MINERVA W ETAL"]
    assert rec["map_number"] == "070-09-01-017"
    assert rec["amount"] == 15733.32


def test_tags_current_sale_date_per_record():
    records = parse_overage_pdf(SAMPLE_TEXT)
    by_name = {r["name"]: r for r in records}
    assert by_name["ANDREWS MINERVA W ETAL"]["tax_sale_date"] == "11/15/2021"
    assert by_name["PRESTON RUTH W ETAL"]["tax_sale_date"] == "10/24/2022"
    assert by_name["LEAKE ROBERT K JR & WYNETTE S"]["tax_sale_date"] == "10/28/2024"


def test_blank_line_between_records_does_not_break_parsing():
    records = parse_overage_pdf(SAMPLE_TEXT)
    by_name = {r["name"]: r for r in records}
    rec = by_name["RAWLINSON DAVID H JR & RAWLINSON ROSALIND L"]
    assert rec["map_number"] == "600-07-01-013"
    assert rec["amount"] == 510.82


def test_boundary_after_dollar_amount_does_not_smear_into_next_name():
    """Regression: '...$9,404.21' immediately followed by the NEXT claimant's
    name line must not be misread as part of the amount or the name."""
    records = parse_overage_pdf(SAMPLE_TEXT)
    by_name = {r["name"]: r for r in records}
    assert by_name["IRVIN BETTY ETAL"]["amount"] == 9404.21
    rec = by_name["LEAKE ROBERT K JR & WYNETTE S"]
    assert rec["map_number"] == "628-11-02-017"
    assert rec["amount"] == 22874.90


def test_unknown_claimant_still_parses_as_a_record():
    """UNKNOWN is a real row in the source data; the scraper (not the parser)
    is responsible for deciding it isn't a usable lead."""
    records = parse_overage_pdf(SAMPLE_TEXT)
    by_name = {r["name"]: r for r in records}
    assert by_name["UNKNOWN"]["map_number"] == "176-00-00-009"


def test_skips_header_and_footer_lines():
    records = parse_overage_pdf(SAMPLE_TEXT)
    for r in records:
        assert r["name"].upper() not in ("NAME", "MAP#", "MAP #", "OVERAGE AMT")
        assert "UPDATED" not in r["name"].upper()


def test_map_number_format():
    import re
    map_re = re.compile(r"^\d{3}-\d{2}-\d{2}-\d{3}$")
    for r in parse_overage_pdf(SAMPLE_TEXT):
        assert map_re.match(r["map_number"]), f"Bad map#: {r['map_number']}"


def test_malformed_map_line_drops_pending_record_without_misattribution():
    """A NAME line followed directly by another NAME-shaped line (no valid
    MAP# in between) must drop the first name rather than pairing it with
    the second name's eventual map/amount."""
    text = """Tax Sale 1/1/2020
NAME
 MAP#
 OVERAGE AMT
BROKEN RECORD NAME
GOOD RECORD NAME
 010-01-01-001
 $100.00
"""
    records = parse_overage_pdf(text)
    names = {r["name"] for r in records}
    assert "GOOD RECORD NAME" in names
    good = next(r for r in records if r["name"] == "GOOD RECORD NAME")
    assert good["map_number"] == "010-01-01-001"
    assert good["amount"] == 100.00
    assert "BROKEN RECORD NAME" not in names


def test_empty_text():
    assert parse_overage_pdf("") == []
    assert parse_overage_pdf("no data here\njust text") == []
