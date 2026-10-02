"""Haywood County tax-foreclosure extraction-completeness audit (2026-10-01).

Two real misses found live: (1) the DocumentCenter notice-PDF link is almost
never on the Bids-module LIST page (confirmed live: the one active posting,
bidID=263, carries no doc link in its list-page block) -- it is only on the
posting's own detail page. (2) even the old best-effort fallback stashed a
found pdf_url only under the nested raw['haywood_tax_foreclosures'] key,
which enrich_doc_ocr's _DOC_FIELDS never reads (it reads TOP-LEVEL
raw['document_url'] / raw['documents'] / raw['pdf_url']) -- so the OCR
backfill this module's own docstring promises (owner/parcel/address from the
scanned notice) was never actually running. Fixed by fetching each posting's
detail page and routing it through the shared harvest_document_links /
stamp_documents helpers."""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_nc import haywood_tax_foreclosures as haywood

# Trimmed, structurally real list-page fixture (one posting, no doc link in
# its block -- matches the live bidID=263 posting captured 2026-10-01).
_BIDS_LIST_HTML = """
<div class="bidItems listItems">
<div class="listItemsRow bid open">
<div class="bidTitle" style="vertical-align: top">
    <span><a href="bids.aspx?bidID=263">Tax Foreclosure Sale October 15, 2026 at 10:00 a.m.</a></span><br>
    <span>Tax Foreclosure Sale October 15th, 2026 at 10:00 a.m.</span>
</div>
<div class="bidStatus">
<div><span>Status:</span><br><span>Closes:</span></div>
<div><span>Open</span><br><span>10/15/2026 10:15 AM</span></div>
</div>
</div>
</div>
<script>var x = 1;</script>
"""

# Trimmed, structurally real detail-page fixture carrying the DocumentCenter
# link the list page omits (filename "Conner" -- the owner's surname).
_DETAIL_HTML = """
<html><body>
<div class="BidDetailSpec">Open</div>
<div class=fr-view>
<span class="BidListHeader">Description:</span>
<span class="BidDetail"><p><a href="/DocumentCenter/View/7948/Conner">Notice of Sale</a></p></span>
</div>
</body></html>
"""


def test_parse_bid_rows_from_list_page():
    rows = haywood._parse_bid_rows(_BIDS_LIST_HTML)
    assert len(rows) == 1
    li = rows[0]
    assert li.sale_date.isoformat()[:10] == "2026-10-15"
    assert li.raw["haywood_tax_foreclosures"]["bid_detail_url"] == (
        "https://www.haywoodcountync.gov/bids.aspx?bidID=263"
    )
    # list page alone carries no doc link -- matches the live page.
    assert li.raw["haywood_tax_foreclosures"]["pdf_url"] is None


def test_enrich_from_detail_wires_pdf_into_top_level_raw(monkeypatch):
    rows = haywood._parse_bid_rows(_BIDS_LIST_HTML)
    li = rows[0]

    async def fake_get_text(url, impersonate=True, timeout=40.0):
        assert url == li.raw["haywood_tax_foreclosures"]["bid_detail_url"]
        return _DETAIL_HTML

    monkeypatch.setattr(haywood, "get_text", fake_get_text)
    asyncio.run(haywood._enrich_from_detail(li))

    # Top-level fields enrich_doc_ocr._DOC_FIELDS actually reads.
    assert li.raw["document_url"] == "https://www.haywoodcountync.gov/DocumentCenter/View/7948/Conner"
    assert li.raw["documents"] == ["https://www.haywoodcountync.gov/DocumentCenter/View/7948/Conner"]
    # Nested debug copy stays in sync too.
    assert li.raw["haywood_tax_foreclosures"]["pdf_url"] == li.raw["document_url"]
    assert li.raw["haywood_tax_foreclosures"]["is_pdf_link"] is True
    assert li.raw["haywood_tax_foreclosures"]["document_filename_hint"] == "Conner"


def test_enrich_from_detail_is_a_noop_without_detail_url(monkeypatch):
    async def fail_get_text(*a, **kw):
        raise AssertionError("should never fetch when there is no detail_url")

    monkeypatch.setattr(haywood, "get_text", fail_get_text)
    li = haywood._parse_bid_rows(_BIDS_LIST_HTML)[0]
    li.raw["haywood_tax_foreclosures"]["bid_detail_url"] = None
    asyncio.run(haywood._enrich_from_detail(li))  # must not raise / not fetch
    assert "documents" not in li.raw
