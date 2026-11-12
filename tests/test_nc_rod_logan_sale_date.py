"""counties_nc.nc_rod_logan — sale_date only on the completed-sale lane.

2026-10-14 (date-coverage audit pass2, item #5 verification): this scraper's "foreclosure_deed"
lane (TR/D, TD, C/TR/D, SHF/D -- a completed sale) never set Listing.sale_date at all before this
fix, same gap found in wnc_rod_foreclosure_starts.py's "trustees_deed" lane. Without a real
sale_date, board_persist._is_terminal_dict() (which runs unconditionally before any
AGE_EXEMPT_SOURCES check) could never fire on a sold row once this source's slug was added to
AGE_EXEMPT_SOURCES, so a completed sale would have sat on the board forever instead of aging out
as settled history. The pre-foreclosure lanes (FCL / LIS/P / S/TR / N/SUB / R/TR) must stay
dateless -- no real sale date is known yet. Made-up names/books; no fetched content.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_nc.nc_rod_logan import _to_listing


class _FakeDoc:
    def __init__(self, doc_type, recorded_date, grantor="SMITH JOHN", grantee="ACME BANK NA",
                 book="1161", page="815", instrument_no=None, notes=None,
                 state="NC", county="Transylvania"):
        self.doc_type = doc_type
        self.recorded_date = recorded_date
        self.grantor = grantor
        self.grantee = grantee
        self.book = book
        self.page = page
        self.instrument_no = instrument_no
        self.notes = notes
        self.state = state
        self.county = county
        self.raw = {}


def test_completed_sale_deed_carries_the_recorded_date_as_sale_date():
    doc = _FakeDoc("TR/D", datetime(2026, 9, 11))
    li = _to_listing(doc, "counties_nc.nc_rod_logan", "https://example.com/logan")
    assert li is not None
    assert li.listing_type == ListingType.FORECLOSURE_SALE
    assert li.sale_date == datetime(2026, 9, 11)


def test_pre_foreclosure_recording_has_no_sale_date():
    doc = _FakeDoc("S/TR", datetime(2026, 9, 11))
    li = _to_listing(doc, "counties_nc.nc_rod_logan", "https://example.com/logan")
    assert li is not None
    assert li.listing_type == ListingType.LIS_PENDENS
    assert li.sale_date is None


def test_lien_recording_has_no_sale_date():
    doc = _FakeDoc("LIEN", datetime(2026, 9, 11))
    li = _to_listing(doc, "counties_nc.nc_rod_logan", "https://example.com/logan")
    assert li is not None
    assert li.listing_type == ListingType.TAX_LIEN
    assert li.sale_date is None
