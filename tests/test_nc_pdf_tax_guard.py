"""Every declared county PDF must account for itself.

Each county here is a four-figure block of leads behind ONE annual .gov PDF
(Catawba 5,256, McDowell 2,260, Lincoln 1,406 as of 2026-08-04). A county whose
document moves leaves a hole big enough to pass for normal shrinkage, and the
old code logged a warning and continued.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

import foreclosure_scraper.scrapers.counties_nc.nc_county_pdf_delinquent_tax as M
from foreclosure_scraper.layer_guard import PartialHarvest

def _blank_pdf() -> bytes:
    """A genuinely valid one-page PDF with no extractable text.

    Hand-rolling the bytes does not work: pypdf needs a real xref table and
    raises PdfReadError("startxref not found"), which the guard then reports as
    a failed layer. Let pypdf write it.
    """
    import io as _io
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    buf = _io.BytesIO()
    w.write(buf)
    return buf.getvalue()


_MIN_PDF = _blank_pdf()


def _resp(status=200, content=b""):
    r = MagicMock()
    r.status_code = status
    r.content = content
    return r


def _fake_client(handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = handler
        yield stub
    return _cm


def test_all_counties_present_is_a_clean_harvest(monkeypatch):
    async def get(url, **kw):
        return _resp(200, _MIN_PDF)
    monkeypatch.setattr(M, "client", _fake_client(get))
    assert list(asyncio.run(M.NCCountyPdfDelinquentTax().fetch())) == []


def test_a_404_county_hard_fails_instead_of_shrinking(monkeypatch):
    """This is the whole point. Before, a moved PDF logged nc_pdf_tax.bad_pdf
    and the source just shipped two counties instead of three."""
    async def get(url, **kw):
        if "mcdowellnc.gov" in url:
            return _resp(404, b"<html>Not Found</html>")
        return _resp(200, _MIN_PDF)
    monkeypatch.setattr(M, "client", _fake_client(get))
    with pytest.raises(PartialHarvest):
        asyncio.run(M.NCCountyPdfDelinquentTax().fetch())


def test_an_html_error_page_served_as_200_hard_fails(monkeypatch):
    """The nastier shape: county returns 200 with an HTML error page, so a
    status check alone passes and pypdf yields nothing. Content must be checked."""
    async def get(url, **kw):
        if "catawbacountync.gov" in url:
            return _resp(200, b"<!DOCTYPE html><title>Page moved</title>")
        return _resp(200, _MIN_PDF)
    monkeypatch.setattr(M, "client", _fake_client(get))
    with pytest.raises(PartialHarvest, match="not a PDF|Catawba"):
        asyncio.run(M.NCCountyPdfDelinquentTax().fetch())


def test_declared_set_is_the_county_list():
    assert set(M.COUNTIES) == {"Lincoln", "Catawba", "McDowell"}
