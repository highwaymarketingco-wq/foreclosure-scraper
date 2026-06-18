"""Verify the Tyler RegisterOfActions parser against a real case fixture
(Henderson County 25M000272 — Julia Taylor Heirs, an already-confirmed sale)."""
from pathlib import Path

from foreclosure_scraper.court_detail_parser import parse_register_of_actions

FIX = Path(__file__).parent / "fixtures" / "tyler_roa_25M000272.txt"


def test_parses_judgment_and_balance():
    out = parse_register_of_actions(FIX.read_text())
    assert out["judgment_amount"] == 1631.64
    assert out["principal_amount"] == 1631.64
    assert out["balance_due"] == 1697.80
    assert out["balance_due_as_of"] == "06/18/2026"


def test_detects_confirmed_sale_status():
    # This case has an Order of Confirmation of Sale → already sold + confirmed.
    out = parse_register_of_actions(FIX.read_text())
    assert out["sale_status"] == "confirmed"


def test_captures_sale_documents_with_dates():
    out = parse_register_of_actions(FIX.read_text())
    by_type = {d["type"]: d for d in out["documents"]}
    assert "Order of Confirmation of Sale" in by_type
    assert by_type["Order of Confirmation of Sale"]["date"] == "06/09/2026"
    assert by_type["Order of Confirmation of Sale"]["available"] is True
    assert "Report of Sale" in by_type
    assert by_type["Report of Sale"]["date"] == "05/28/2026"
    assert "Notice Of Sale/Resale" in by_type


def test_works_on_raw_html_too():
    html = "<div><span>Total Judgment:</span> $2,500.00</div><p>Report of Sale</p>"
    out = parse_register_of_actions(html)
    assert out["judgment_amount"] == 2500.00
    assert out["sale_status"] == "sold_unconfirmed"
