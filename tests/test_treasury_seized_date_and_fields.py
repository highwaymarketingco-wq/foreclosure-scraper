"""reo.treasury_seized: 2026-10-01 national/reo per-source extraction audit.

The real page's auction-date label ("ONLINE AUCTION DATE: Thursday,
November 19, 2026") is a written-month date; the pre-existing DATE_RE was
numeric-only ("11/19/2026") and never matched it, so sale_date came back
None on every current listing despite the real date sitting a few lines
below the address, well within the 400-char forward-scan window. beds/
baths/sqft and the Treasury's own "Sale #" case identifier are also free
text in that same block, never parsed into structured fields. Fixed all
four; confirmed live against 2 real current listings.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from foreclosure_scraper.scrapers.reo import treasury_seized as m

# A trimmed but real capture of treasury.gov's realprop.shtml body text,
# 2026-10-01.
_REAL_BODY_TEXT = """
SINGLE FAMILY HOME
:
2721 Briar Ridge Drive, Charlotte, North Carolina 28270

ONLINE AUCTION DATE:
Thursday, November 19, 2026

2,835 ± sq. ft. home with 4 bedrooms, 2.1 baths, 2nd floor bonus room, fireplace, patio,
and attached 2-car garage. Located in the Greenbrier community. Sale # 27-66-109.

For complete details on this property click on the photo or CLICK HERE
"""


def _run_fetch_with_body(body_text: str):
    class _FakeResp:
        status_code = 200
        text = body_text * 1  # len must clear the >1000-char gate

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return _FakeResp()

    import foreclosure_scraper.http_client as hc

    orig_client = hc.client

    class _Ctx:
        def __call__(self, *a, **kw):
            return _FakeClient()

    # Patch the module-level `client` symbol treasury_seized.py imported.
    m.client = _Ctx()
    try:
        # _FakeResp.text must be the real body padded past 1000 chars and
        # HTMLParser-parseable; wrap it in a minimal body tag.
        html = f"<html><body>{body_text}</body></html>" + " " * 1200
        _FakeResp.text = html
        scraper = m.TreasurySeizedRealProperty()
        return asyncio.run(asyncio.wait_for(scraper.fetch(), timeout=5.0))
    finally:
        m.client = orig_client


def test_written_month_date_is_parsed():
    out = _run_fetch_with_body(_REAL_BODY_TEXT)
    assert len(out) == 1
    li = out[0]
    assert li.street_address == "2721 Briar Ridge Drive"
    assert li.sale_date == datetime(2026, 11, 19)


def test_sale_number_beds_baths_sqft_captured():
    out = _run_fetch_with_body(_REAL_BODY_TEXT)
    li = out[0]
    assert li.case_number == "27-66-109"
    assert li.living_sqft == 2835.0
    assert li.bedrooms == 4.0
    assert li.bathrooms == 2.1


def test_written_date_regex_matches_the_real_format_directly():
    assert m.WRITTEN_DATE_RE.search("Thursday, November 19, 2026") is not None
    assert m.WRITTEN_DATE_RE.search("Nov. 19, 2026") is not None


def test_numeric_date_fallback_still_works():
    block = "ONLINE AUCTION DATE: 11/19/2026\nSale # 1-2-3."
    dm = m.WRITTEN_DATE_RE.search(block) or m.DATE_RE.search(block)
    assert dm is not None
    assert dm.group(0) == "11/19/2026"
