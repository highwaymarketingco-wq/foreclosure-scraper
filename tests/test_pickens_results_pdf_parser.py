"""Pin Pickens MIE results-PDF sold-price extraction.

Pickens publishes monthly RESULTS PDFs (e.g. "APRIL 2026 - RESULTS.pdf",
"MARCH 2026 DEFICIENCY - RESULTS.pdf") that report past sales with
hammer prices. The scraper downloads these but the parser previously
only extracted case# + address. These tests pin the new sold-price
extraction so it doesn't silently regress.

Live PDF text format varies — the regexes here cover the common shapes
SC MIE results PDFs use. Tests use synthetic chunks since the live
PDFs are behind a session-cookie + redirect dance and only fetchable
from the GitHub Actions runner with Scrapling Chromium.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc.pickens_master_in_equity import (
    _extract_sold_price,
    _is_results_pdf,
)


# ---- _is_results_pdf detection ----

def test_results_pdf_detected_from_url():
    assert _is_results_pdf("https://example.com/APRIL 2026 - RESULTS.pdf") is True


def test_results_pdf_detected_from_label():
    assert _is_results_pdf("https://x.pdf", "March 2026 RESULTS") is True


def test_upcoming_pdf_not_detected():
    """Upcoming-sale roster (no RESULTS marker) should NOT be tagged
    as a results PDF — its prices are opening bids, not hammer prices."""
    assert _is_results_pdf("https://example.com/MAY 2026 ROSTER.pdf") is False


def test_deficiency_results_pdf_detected():
    """Pickens publishes 'X DEFICIENCY - RESULTS.pdf' for deficiency
    auctions — those are also sold-price PDFs."""
    assert _is_results_pdf(
        "https://x/MARCH 2026 DEFICIENCY - RESULTS.pdf"
    ) is True


# ---- _extract_sold_price patterns ----

def test_high_bid_pattern():
    chunk = "2024-CP-39-12345 SMITH JOHN 123 MAIN ST High Bid: $45,000"
    price, src = _extract_sold_price(chunk)
    assert price == 45000.0


def test_sold_for_pattern():
    chunk = "2024-CP-39-99999 BROWN JANE 555 OAK AVE Sold to ABC LLC for $32,500"
    price, _ = _extract_sold_price(chunk)
    assert price == 32500.0


def test_final_bid_pattern():
    chunk = "2024-CP-39-11111 Final Bid: $128,750.00 Property at 100 Pine St"
    price, _ = _extract_sold_price(chunk)
    assert price == 128750.0


def test_bid_amount_pattern():
    chunk = "2024-CP-39-22222 Successful Bid Amount: $87,500"
    price, _ = _extract_sold_price(chunk)
    assert price == 87500.0


def test_sale_price_pattern():
    chunk = "2024-CP-39-33333 Sale Price: $19,000.50"
    price, _ = _extract_sold_price(chunk)
    assert price == 19000.50


def test_money_then_sold_keyword_pattern():
    chunk = "2024-CP-39-44444 100 Maple Dr $52,750 SOLD"
    price, _ = _extract_sold_price(chunk)
    assert price == 52750.0


def test_upset_bid_wins_over_initial_bid():
    """Pickens shows successive upset bids — we want the FINAL hammer
    price, which is the highest upset bid."""
    chunk = (
        "2024-CP-39-55555 SMITH "
        "High Bid: $40,000 "
        "Upset Bid: $45,000 "
        "Upset Bid: $50,000"
    )
    price, src = _extract_sold_price(chunk)
    assert price == 50000.0
    assert src == "upset_bid"


def test_withdrawn_status_returns_none():
    """No actual sale happened — don't claim a sold price for these."""
    chunk = "2024-CP-39-66666 SMITH 100 Main St $40,000 WITHDRAWN"
    price, src = _extract_sold_price(chunk)
    assert price is None
    assert src == "non_sale_status"


def test_postponed_status_returns_none():
    chunk = "2024-CP-39-77777 SMITH 100 Main St POSTPONED to next month"
    price, _ = _extract_sold_price(chunk)
    assert price is None


def test_dismissed_status_returns_none():
    chunk = "2024-CP-39-88888 SMITH 100 Main St DISMISSED — no sale"
    price, _ = _extract_sold_price(chunk)
    assert price is None


def test_no_bid_status_returns_none():
    chunk = "2024-CP-39-99999 SMITH 100 Main St NO BID — returned to plaintiff"
    price, _ = _extract_sold_price(chunk)
    assert price is None


def test_implausible_amount_rejected():
    """A $50 'sold price' is almost certainly a parse error — court fees
    or filing costs, not a real hammer price."""
    chunk = "2024-CP-39-12345 Sale Price: $50"
    price, _ = _extract_sold_price(chunk)
    assert price is None


def test_too_large_amount_rejected():
    """$50M+ in a Pickens SC foreclosure is almost certainly a regex
    misfire (e.g. caught a phone number or zip)."""
    chunk = "2024-CP-39-12345 Sale Price: $50,000,000"
    price, _ = _extract_sold_price(chunk)
    assert price is None


def test_no_pattern_match_returns_none():
    """Chunk with case# + address but no money figure at all."""
    chunk = "2024-CP-39-12345 SMITH JOHN 100 Main St Pickens"
    price, src = _extract_sold_price(chunk)
    assert price is None
    assert src == "no_match"
