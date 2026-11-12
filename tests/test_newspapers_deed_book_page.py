"""hendersonville_lightning / shelby_star / tryon_bulletin — Deed of Trust
book/page extraction.

FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers batch 2):
real NC substitute-trustee notices state the foreclosed Deed of Trust's
recording reference in prose -- live-confirmed on 2 real current
hendersonville_lightning.py notices:
  "...recorded June 30, 2008 in Deed of Trust Book 2088, at Page 656 of the
  Henderson County Registry and in Book 366, at Page 240 of the Polk County
  Registry..."
  "...recorded on January 5, 2001 in Book 935 at Page 148, Henderson County
  Registry, North Carolina."
Never captured on any of the 3 scrapers that share this notice shape. Wired
as `deed_book`/`deed_page` under each scraper's existing per-row raw key.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.newspapers import hendersonville_lightning as hvl
from foreclosure_scraper.scrapers.newspapers import shelby_star as ss
from foreclosure_scraper.scrapers.newspapers import tryon_bulletin as tb

# Real captured shape (Hendersonville Lightning, 2026-10-04 live fetch).
HVL_HTML = """<html><body>
<h3 class="title">NOTICE OF FORECLOSURE SALE, FILE NO. 2016-SP-99</h3>
<p>NORTH CAROLINA, HENDERSON COUNTY FILE NO. 2016-SP-99 Under and by virtue of a Power of
Sale contained in that certain Deed of Trust executed by Kevin Sampleton and Denise Sampleton, which
was dated September 28, 2000 and recorded on January 5, 2001 in Book 935 at Page 148,
Henderson County Registry, North Carolina. Property address: 100 Example Rd, Hendersonville,
NC 28792. The sale will take place on October 28, 2026, at 2:00 PM.</p>
</body></html>"""


def test_hendersonville_lightning_captures_deed_book_page(monkeypatch):
    async def fake_get(self, url, headers=None):
        class R:
            status_code = 200
            text = HVL_HTML
        return R()

    import foreclosure_scraper.http_client as hc

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, headers=None):
            class R:
                status_code = 200
                text = HVL_HTML
            return R()

    monkeypatch.setattr(hvl, "client", lambda timeout=20.0: FakeClient())
    out = asyncio.run(hvl.HendersonvilleLightningForeclosures().fetch())
    assert len(out) == 1
    assert out[0].raw["hendersonville_lightning"]["deed_book"] == "935"
    assert out[0].raw["hendersonville_lightning"]["deed_page"] == "148"


def test_deed_book_page_regex_matches_both_real_shapes():
    assert hvl.DEED_BOOK_PAGE_RE.search(
        "recorded June 30, 2008 in Deed of Trust Book 2088, at Page 656 of the "
        "Henderson County Registry"
    ).groups() == ("2088", "656")
    assert hvl.DEED_BOOK_PAGE_RE.search(
        "recorded on January 5, 2001 in Book 935 at Page 148, Henderson County Registry"
    ).groups() == ("935", "148")


def test_shelby_star_has_the_same_regex():
    assert ss.DEED_BOOK_PAGE_RE.search(
        "recorded on January 5, 2001 in Book 935 at Page 148, Cleveland County Registry"
    ).groups() == ("935", "148")


def test_tryon_bulletin_has_the_same_regex():
    assert tb.DEED_BOOK_PAGE_RE.search(
        "recorded on January 5, 2001 in Book 935 at Page 148, Polk County Registry"
    ).groups() == ("935", "148")
