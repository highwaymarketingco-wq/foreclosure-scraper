"""Test the SC Public Index case detail parser (selectolax-based).

Uses the real saved sample /tmp/sc_case_detail_sample.html (case 2024CP0402575,
Anderson County, St Franklin Financial VS Amy Buchanan — a magistrate judgment).
If that file is absent (e.g. CI without /tmp fixture), tests are skipped.
"""
from pathlib import Path

import pytest

from foreclosure_scraper.court_detail_parser import parse_sc_case_detail

FIX = Path("/tmp/sc_case_detail_sample.html")


@pytest.fixture
def html():
    if not FIX.exists():
        pytest.skip(f"fixture {FIX} not found")
    return FIX.read_text(errors="replace")


def test_parses_case_caption(html):
    out = parse_sc_case_detail(html)
    assert "VS" in out["case_caption"]
    assert "Buchanan" in out["case_caption"]


def test_extracts_case_number(html):
    out = parse_sc_case_detail(html)
    assert out["case_number"] == "2024CP0402575"


def test_extracts_judgment_amount(html):
    out = parse_sc_case_detail(html)
    assert out["judgment_amount"] == 1550.88


def test_extracts_balance_due(html):
    out = parse_sc_case_detail(html)
    assert out["balance_due"] == 0.0


def test_extracts_parties(html):
    out = parse_sc_case_detail(html)
    parties = out["parties"]
    assert len(parties) >= 2
    names = {p["name"] for p in parties}
    assert "Buchanan, Amy" in names
    types = {p["party_type"] for p in parties}
    assert "Defendant" in types or "Defendant Pro Se" in types


def test_extracts_docket(html):
    out = parse_sc_case_detail(html)
    assert len(out["docket"]) >= 1
    entry = out["docket"][0]
    assert entry["description"]  # non-empty
    assert entry["begin_date"]


def test_extracts_costs(html):
    out = parse_sc_case_detail(html)
    costs = out["costs"]
    assert len(costs) == 1
    assert costs[0]["cost_code"] == "TRANSJ"
    assert costs[0]["amount"] == 35.0


def test_extracts_payments(html):
    out = parse_sc_case_detail(html)
    pmts = out["payments"]
    assert len(pmts) == 1
    assert pmts[0]["receipt_number"] == "144164"
    assert pmts[0]["payment_amount"] == 35.0


def test_works_on_empty_html():
    assert parse_sc_case_detail("") == {}
    assert parse_sc_case_detail("<html></html>") == {}


def test_falls_back_to_regex_for_non_sc_html():
    """If the HTML has no detailsSection tables, fall back to the regex parser."""
    html = "<div><span>Total Judgment:</span> $2,500.00</div><p>Report of Sale</p>"
    out = parse_sc_case_detail(html)
    assert out.get("judgment_amount") == 2500.0
    assert out.get("sale_status") == "sold_unconfirmed"
