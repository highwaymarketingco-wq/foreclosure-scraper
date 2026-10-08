"""counties_nc.wnc_tax_foreclosures: Madison's own tax-foreclosure page (2026-10-08).

Madison's homepage has no foreclosure link; its first "tax" links are a PDF, the ArcGIS tax map
and lrcpwa.ncptscloud.com/Madison (a JavaScript app that timed out on the VM). The scraper now
reads the county's Tax Foreclosure Sales page directly and never follows vendor-app / PDF links.
HTML below is invented in the real shapes.
"""
from __future__ import annotations

import asyncio

import foreclosure_scraper.scrapers.counties_nc.wnc_tax_foreclosures as m

HOME = ("<html><body>" + "x" * 300 +
        '<a href="/uploads/1/2/occupancy_tax_report.pdf">ROOM OCCUPANCY TAX REPORT</a>'
        '<a href="http://experience.arcgis.com/experience/abc">Tax Maps</a>'
        '<a href="http://lrcpwa.ncptscloud.com/Madison">Property Tax Search</a>'
        '<a href="https://www.govpayments.com/nc_madison">Online Tax Payments</a>'
        "</body></html>")

SALE_PAGE = ("<html><body><h2>Tax Foreclosure Sales</h2>"
             "<table><tr><td>PARCEL</td><td>OPENING BID</td></tr>"
             "<tr><td>9700-12-3456</td><td>$1,234.00</td></tr></table>"
             '<table class="wsite-multicol-table"><tr><td>Home</td><td>Departments</td>'
             "<td>Commissioners</td></tr></table></body></html>")


def _run(monkeypatch, pages):
    seen = []

    async def fake(url, **kw):
        seen.append(url)
        return pages.get(url)

    monkeypatch.setattr(m, "get_text", fake)
    monkeypatch.setattr(m, "COUNTIES", {"Madison": "https://www.madisoncountync.gov/"})
    out = asyncio.run(m.WNCTaxForeclosures().fetch())
    return out, seen


def test_madison_reads_its_tax_foreclosure_page_and_skips_vendor_apps(monkeypatch):
    out, seen = _run(monkeypatch, {"https://www.madisoncountync.gov/": HOME,
                                   m.COUNTY_TAX_PAGES["Madison"][0]: SALE_PAGE})
    assert m.COUNTY_TAX_PAGES["Madison"][0] in seen
    assert not any("ncptscloud" in u or "arcgis" in u or u.endswith(".pdf") for u in seen)
    assert [(li.parcel_id, li.judgment_amount) for li in out] == [("9700-12-3456", 1234.0)]


def test_a_layout_table_is_not_a_sale_row(monkeypatch):
    out, _ = _run(monkeypatch, {m.COUNTY_TAX_PAGES["Madison"][0]: SALE_PAGE.replace(
        "<tr><td>9700-12-3456</td><td>$1,234.00</td></tr>", "")})
    assert out == []


def test_the_direct_page_is_read_even_when_the_homepage_fails(monkeypatch):
    out, seen = _run(monkeypatch, {m.COUNTY_TAX_PAGES["Madison"][0]: SALE_PAGE})
    assert len(out) == 1 and seen[-1] == m.COUNTY_TAX_PAGES["Madison"][0]
