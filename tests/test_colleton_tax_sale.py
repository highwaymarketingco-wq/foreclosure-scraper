"""Tests for Colleton County SC tax-sale PDF discovery/selection.

2026-10-03 fix: the tax-sale page can carry TWO real parcel-list PDFs at once
(a current, visibly-linked one and a stale orphaned one left over from a CMS
edit), and the old discovery logic picked the stale one because its filename
matched the ranking heuristic more strongly than the real, current file. See
colleton_tax_sale.py's fetch() docstring for the live-verified details.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.scrapers.counties_sc.colleton_tax_sale import (
    _discover_list_pdf,
    _filename_date,
    parse_list,
)

# Real markup shape fetched live 2026-10-03 from
# https://www.colletoncounty.org/delinquent-tax/tax-sale -- the REAL, human-
# visible link ("here") is taxsale-1-30-26.pdf; the orphaned, invisible
# (single-space anchor text) link is the stale taxsalelist-01-29.pdf.
_REAL_PAGE_FRAGMENT = (
    '<p><strong>Colleton County Delinquent Tax Office</strong><br>'
    '<strong>2025 Tax Sale Information</strong></p>'
    '<ul><li>Click '
    '<a href="/sites/default/files/uploads/taxsale-1-30-26.pdf"><strong>here</strong></a>'
    '<a href="/sites/default/files/uploads/del_tax/taxsalelist-01-29.pdf"> </a>'
    'to view Tax Sale Property Listings.</li>'
    '<li><a href="/sites/default/files/uploads/del_tax/bidder-registration.pdf">'
    'Bidder Registration Form</a></li></ul>'
)

# Real column header + 2 real rows from each live PDF (2026-10-03), trimmed.
_PDF_TEXT_01_29 = (
    "Owner Name Map Number Description Acres Total Tax Due\n"
    "A H CONCRETE LLC A SOUTH CAROLINA LIMITE 136-00-00-232.000 Lot 21 Tract S-242 RHODE DR (D 2 497.8\n"
    "ACKERMAN ARTHUR JAMES 180-00-00-399.002 2000 HORTON/MIRAGE 14X68 VIN# H172726G DECAL#: 0 940.57\n"
)
_PDF_TEXT_01_30 = (
    "Owner Name Map Number Description Acres Total Tax Due\n"
    "ACKERMAN ARTHUR JAMES 180-00-00-399.002 2000 HORTON/MIRAGE 14X68 VIN# H172726G DECAL#: 0 940.57\n"
)


def test_filename_date_parses_month_day_year():
    d = _filename_date("https://www.colletoncounty.org/sites/default/files/uploads/taxsale-1-30-26.pdf")
    assert d == datetime(2026, 1, 30)


def test_filename_date_parses_month_day_only_using_current_year():
    d = _filename_date(
        "https://www.colletoncounty.org/sites/default/files/uploads/del_tax/taxsalelist-01-29.pdf"
    )
    assert d is not None
    assert (d.month, d.day) == (1, 29)
    assert d.year == datetime.utcnow().year


def test_filename_date_returns_none_when_no_date_embedded():
    assert _filename_date("https://www.colletoncounty.org/sites/default/files/uploads/taxsalelist.pdf") is None


def test_discover_ranks_the_stale_ghost_link_above_the_real_one():
    """Pinning the BUG this fix works around: _discover_list_pdf's scoring alone
    (filename-only) still ranks the orphaned taxsalelist-01-29.pdf first -- the
    real fix lives in fetch()'s candidate-date comparison, not in the ranker,
    so this stays red/documents-the-quirk rather than asserting the old (wrong)
    behavior is desirable."""
    cands = _discover_list_pdf(_REAL_PAGE_FRAGMENT)
    assert cands[0].endswith("taxsalelist-01-29.pdf")
    assert any(u.endswith("taxsale-1-30-26.pdf") for u in cands)
    # the bidder registration form must never outrank (or even tie into) either
    # real listing candidate
    assert not any("bidder" in u for u in cands[:2])


def test_parse_list_shows_the_two_pdfs_genuinely_differ():
    rows_29 = parse_list(_PDF_TEXT_01_29, "https://x/taxsalelist-01-29.pdf", None)
    rows_30 = parse_list(_PDF_TEXT_01_30, "https://x/taxsale-1-30-26.pdf", None)
    assert len(rows_29) == 2
    assert len(rows_30) == 1
    tms_29 = {r.parcel_id for r in rows_29}
    tms_30 = {r.parcel_id for r in rows_30}
    # the stale file carries a real parcel (A H CONCRETE LLC, 136-00-00-232.000)
    # that the newer file has already dropped -- almost certainly paid/redeemed.
    assert "136-00-00-232.000" in tms_29
    assert "136-00-00-232.000" not in tms_30
