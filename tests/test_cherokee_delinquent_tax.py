"""Tests for Cherokee SC delinquent tax sale PDF parser."""
from foreclosure_scraper.scrapers.counties_sc.cherokee_delinquent_tax import _parse_pdf_text


SAMPLE_TEXT = """DELINQUENT TAX SALE
Legal Notice of Delinquent Tax Sale
State of South Carolina, Cherokee County
NOTICE: THE DELINQUENT TAX SALE OF CHEROKEE COUNTY WILL BE HELD ON MONDAY NOVEMBER 4, 2024

Item Number Owner Name Map Number Description
1 A AND R PROPERTY MANAGEMENT 099-01-00-022.000 946 N LOGAN ST
2 A.T.O. 21 LLC 081-12-00-025.000 W FAIRVIEW AVE//800 1/2
3 A.T.O. 21 LLC 081-14-00-031.000 417 MARION AVE
4 A.T.O. 21 LLC 099-06-00-133.000 604 RAILROAD AVE LT#6 B
6 A.T.O. 21 LLC 118-05-00-028.000 730 MARIETTA ST
106-00-00-018.002 ADAMS ZAVIAH 4701 UNION HWY
032-00-00-112.102 ALEJO PABLE ANTONIO 121 C B LN
"""


def test_parses_standard_rows():
    """Standard rows: <item#> <owner> <TMS> <description>"""
    rows = _parse_pdf_text(SAMPLE_TEXT)
    # Should parse rows that start with item number
    tms_values = [r["tms"] for r in rows]
    assert "099-01-00-022.000" in tms_values
    assert "081-12-00-025.000" in tms_values


def test_extracts_owner():
    rows = _parse_pdf_text(SAMPLE_TEXT)
    owners = {r["tms"]: r["owner"] for r in rows}
    assert owners.get("099-01-00-022.000") == "A AND R PROPERTY MANAGEMENT"
    assert owners.get("081-12-00-025.000") == "A.T.O. 21 LLC"


def test_extracts_description():
    rows = _parse_pdf_text(SAMPLE_TEXT)
    descs = {r["tms"]: r["description"] for r in rows}
    assert "946 N LOGAN ST" in descs.get("099-01-00-022.000", "")


def test_skips_header_lines():
    rows = _parse_pdf_text(SAMPLE_TEXT)
    # No row should have "Item Number" as owner
    for r in rows:
        assert "Item Number" not in r["owner"]
        assert "DELINQUENT" not in r["owner"].upper()


def test_empty_text():
    assert _parse_pdf_text("") == []
    assert _parse_pdf_text("No data here\njust text") == []


def test_tms_format():
    """TMS should match NNN-NN-NN-NNN.NNN format"""
    rows = _parse_pdf_text(SAMPLE_TEXT)
    import re
    tms_re = re.compile(r"^\d{3}-\d{2}-\d{2}-\d{3}\.\d{3}$")
    for r in rows:
        assert tms_re.match(r["tms"]), f"Bad TMS: {r['tms']}"
