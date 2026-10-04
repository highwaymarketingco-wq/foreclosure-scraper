"""Spartanburg Master-in-Equity wide-table row parsing, incl. the 2026-10-04
cancelled-row fix (extraction-completeness audit, batch 13).

Live-verified shape (2026-10-04): the current Sale-Results.pdf's
pdfplumber.extract_tables() rows look like
  ['1.', '_____', '26-1844', 'St Amand, Thompson', 'First Piedmont Federal',
   'Hyde, Jonathan\\n292 Harrell Drive, Sptbg., SC', '________________',
   '______________________', '√']
for a CANCELLED case -- case#/attorney/plaintiff/defendant/address are all
real; only Bid/BidBy are the blank placeholder. 16 of 47 wide rows in that
PDF carry the "√" marker. These used to be dropped outright.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_sc.spartanburg_master_in_equity import (
    _wide_row_to_listing,
)

_SOURCE_URL = "https://www.spartanburgcounty.gov/DocumentCenter/View/3392/Sale-Results"
_SALE_DATE = datetime(2026, 9, 8)


def test_cancelled_row_is_kept_not_dropped():
    row = ["1.", "_____", "26-1844", "St Amand, Thompson", "First Piedmont Federal",
           "Hyde, Jonathan\n292 Harrell Drive, Sptbg., SC",
           "________________", "______________________", "√"]
    li = _wide_row_to_listing(row, _SOURCE_URL, True, _SALE_DATE, set())
    assert li is not None
    assert li.case_number == "26-1844"
    assert li.defendant == "Hyde, Jonathan"
    assert li.street_address == "292 Harrell Drive, Sptbg., SC"
    assert li.plaintiff == "First Piedmont Federal"
    assert li.auction_status == "cancelled"
    assert li.opening_bid is None
    assert li.raw["spartanburg_pdf"]["cancelled"] is True
    assert "actual_sold_price" not in li.raw
    assert li.listing_type is ListingType.FORECLOSURE_SALE


def test_cancelled_row_never_claims_a_sold_price():
    """Even if a stray '$' ever showed up in a cancelled row's Bid cell, a
    cancelled sale must never report actual_sold_price (it never happened)."""
    row = ["2.", "_____", "26-9999", "Firm", "Plaintiff Bank",
           "Doe, Jane\n1 Main St, Sptbg, SC",
           "$123,456.00", "______________________", "√"]
    li = _wide_row_to_listing(row, _SOURCE_URL, True, _SALE_DATE, set())
    assert li.auction_status == "cancelled"
    # Documents today's actual behavior: bid still parses off the row (the
    # cancelled flag doesn't blank an unexpected real-looking bid cell) --
    # this scenario has never been observed live (real cancelled rows always
    # carry the blank placeholder), so opening_bid reflects whatever the cell
    # says. What must NOT happen is actual_sold_price being set on a results
    # PDF when the row is marked cancelled.
    assert "actual_sold_price" not in li.raw


def test_non_cancelled_row_keeps_normal_status():
    row = ["2.", "Final", "26-0714", "Firm", "Plaintiff Bank",
           "Malibu Real Estate Inv.\n686 California Ave., Sptbg, SC",
           "$265,000.00", "Plaintiff"]
    li = _wide_row_to_listing(row, _SOURCE_URL, True, _SALE_DATE, set())
    assert li.auction_status == "final"
    assert li.opening_bid == 265000.0
    assert li.raw["spartanburg_pdf"]["cancelled"] is False
    assert li.raw["actual_sold_price"] == 265000.0


def test_header_row_returns_none():
    row = ["#", "Status", "Case #", "Attorney", "Plaintiff", "Defendant", "Bid", "Bid By"]
    assert _wide_row_to_listing(row, _SOURCE_URL, True, _SALE_DATE, set()) is None


def test_duplicate_case_number_returns_none():
    seen = {"26-0714"}
    row = ["2.", "Final", "26-0714", "Firm", "Plaintiff Bank",
           "Someone\n1 St, Sptbg, SC", "$1.00", "Plaintiff"]
    assert _wide_row_to_listing(row, _SOURCE_URL, True, _SALE_DATE, seen) is None


def test_no_case_number_returns_none():
    row = ["1.", "_____", "", "Firm", "Bank", "Name\nAddr", "___", "___", "√"]
    assert _wide_row_to_listing(row, _SOURCE_URL, True, _SALE_DATE, set()) is None
