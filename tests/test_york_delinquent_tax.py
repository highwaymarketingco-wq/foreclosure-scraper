"""York County SC delinquent-tax scraper.

AUDITED 2026-10-01: the document-link fallback used to emit a bare,
content-free placeholder Listing for ANY matched DocumentCenter link whose
label looked list-like -- including "OVERAGE-CLAIM-LIST", which is actually
counties_sc.york_overage_claims.py's own document. Live, this was the only
match (no real per-parcel delinquent list is posted right now), so the
scraper's entire output was one useless duplicate row (no owner, no parcel,
no address). Fixed to (a) exclude overage-claim documents and (b) actually
download and table-parse a matched list PDF instead of just linking to it.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from foreclosure_scraper.scrapers.counties_sc.york_delinquent_tax import YorkDelinquentTax

_LANDING_OVERAGE_ONLY = """
<html><body>
<a href="/DocumentCenter/View/5241/Tax-Sale-Fact-Sheet">Tax Sale Fact Sheet</a>
<a href="/DocumentCenter/View/2828/OVERAGE-CLAIM-LIST">OVERAGE CLAIM LIST</a>
<a href="/DocumentCenter/View/7271/Installment-Guidelines">Installment Guidelines</a>
</body></html>
""" + "x" * 200

_LANDING_WITH_REAL_LIST = """
<html><body>
<a href="/DocumentCenter/View/2828/OVERAGE-CLAIM-LIST">OVERAGE CLAIM LIST</a>
<a href="/DocumentCenter/View/9999/2026-Delinquent-Tax-Sale-List">2026 Delinquent Tax Sale List</a>
</body></html>
""" + "x" * 200


def test_overage_claim_document_is_never_matched(monkeypatch):
    """Only an Overage-Claim document is on the page -> must yield 0 rows,
    not a bare placeholder pointing at york_overage_claims.py's own document."""
    import foreclosure_scraper.scrapers.counties_sc.york_delinquent_tax as m

    async def fake_get_text(*a, **k):
        return _LANDING_OVERAGE_ONLY

    monkeypatch.setattr(m, "get_text", fake_get_text)
    rows = asyncio.run(YorkDelinquentTax().fetch())
    assert list(rows) == []


def test_real_list_document_is_downloaded_and_table_parsed(monkeypatch):
    """A genuine 'Delinquent Tax Sale List' document must be fetched and
    table-parsed into real Listings, not recorded as a bare link."""
    import foreclosure_scraper.scrapers.counties_sc.york_delinquent_tax as m

    async def fake_get_text(*a, **k):
        return _LANDING_WITH_REAL_LIST

    class FakeResp:
        status_code = 200
        content = b"PDF-BYTES-PLACEHOLDER"

    class FakeClientCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResp()

    class FakeTable:
        def extract_tables(self):
            return [[
                ["Owner", "TMS", "Address", "Amount Due"],
                ["SMITH JOHN", "123-45-67-890", "101 Main St", "$543.21"],
            ]]

    class FakePdf:
        pages = [FakeTable()]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(m, "get_text", fake_get_text)
    monkeypatch.setattr(m, "client", lambda timeout=None: FakeClientCtx())

    import sys
    import types
    fake_pdfplumber = types.ModuleType("pdfplumber")
    fake_pdfplumber.open = lambda *a, **k: FakePdf()
    with patch.dict(sys.modules, {"pdfplumber": fake_pdfplumber}):
        rows = asyncio.run(YorkDelinquentTax().fetch())

    rows = list(rows)
    assert len(rows) == 1
    assert rows[0].defendant == "SMITH JOHN"
    assert rows[0].parcel_id == "123-45-67-890"
    assert rows[0].street_address == "101 Main St"
    assert rows[0].opening_bid == 543.21


def test_pdf_with_no_matching_table_yields_nothing(monkeypatch):
    """A matched document that doesn't actually contain a parseable table
    must not ship a fabricated placeholder row."""
    import foreclosure_scraper.scrapers.counties_sc.york_delinquent_tax as m

    async def fake_get_text(*a, **k):
        return _LANDING_WITH_REAL_LIST

    class FakeResp:
        status_code = 200
        content = b"PDF-BYTES-PLACEHOLDER"

    class FakeClientCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResp()

    class FakeTable:
        def extract_tables(self):
            return []  # no tables at all in this PDF

    class FakePdf:
        pages = [FakeTable()]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(m, "get_text", fake_get_text)
    monkeypatch.setattr(m, "client", lambda timeout=None: FakeClientCtx())

    import sys
    import types
    fake_pdfplumber = types.ModuleType("pdfplumber")
    fake_pdfplumber.open = lambda *a, **k: FakePdf()
    with patch.dict(sys.modules, {"pdfplumber": fake_pdfplumber}):
        rows = asyncio.run(YorkDelinquentTax().fetch())
    assert list(rows) == []
