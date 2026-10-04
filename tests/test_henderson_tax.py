"""Henderson County NC tax-foreclosure-sales extraction-completeness audit
(2026-10-03).

The "Clerk of Court File #" cell wraps its text in a real <a href> to the NC
eCourts "Register of Actions" portal page for that case -- live-confirmed on
every current row (county's own page, captured 2026-10-03). The old parser
read only the cell's visible text (the case number) and discarded the href.
Fixture mirrors the real live table shape (owner/parcel/case changed)."""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_nc import henderson_tax as m

_CASE_URL = (
    "https://portal-nc.tylertech.cloud/app/RegisterOfActions/#/"
    "1766B1E1512D415FFDD9CE146B4C7BDB6EBCD43D129220F224B28A8D021A85B3/"
    "anon/portalembed"
)

_PAGE_HTML = f"""
<html><body>
<p>Sale will be held May 27, 2026 at 10:00am at 200 N Grove St, Hendersonville, NC 28792.</p>
<table>
<tr>
<th>Listing Owner's Name:</th><th>Parcel #:</th><th>Description:</th>
<th>&nbsp; &nbsp; Clerk of Court File #&nbsp; &nbsp;&nbsp;</th><th>Estimated Opening Bid*</th>
</tr>
<tr>
<th>CASE, GREGORY P HEIRS</th>
<th>301249</th>
<th><p>L#4 SEC B HUCKLEBERRY WEST SE:B</p></th>
<th><a href="{_CASE_URL}">25M000267-440</a></th>
<th>$777.17*</th>
</tr>
<tr>
<th>CARRIAGE PARK ASSOCIATES LLC</th>
<th>1001870</th>
<th><p>CARRIAGE SPRINGS LO:12 PH:II SE:9</p></th>
<th>25M000266-440</th>
<th>$4,344.82*</th>
</tr>
</table>
</body></html>
"""


class _FakeResp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


class _FakeHttpxClient:
    def __init__(self, text: str):
        self._text = text

    async def get(self, url, headers=None):
        return _FakeResp(self._text)


class _Ctx:
    def __init__(self, c):
        self._c = c

    async def __aenter__(self):
        return self._c

    async def __aexit__(self, *a):
        return False


def _run_fetch(html: str, monkeypatch):
    monkeypatch.setattr(m, "client", lambda *a, **kw: _Ctx(_FakeHttpxClient(html)))
    monkeypatch.delenv(m.ENV_OFF, raising=False)
    return asyncio.run(m.HendersonTaxForeclosure().fetch())


def test_linked_row_captures_the_ecourts_case_detail_url(monkeypatch):
    rows = _run_fetch(_PAGE_HTML, monkeypatch)
    assert len(rows) == 2
    linked = next(li for li in rows if li.parcel_id == "301249")
    assert linked.raw["henderson_tax"]["case_detail_url"] == _CASE_URL


def test_unlinked_row_has_no_fabricated_url(monkeypatch):
    rows = _run_fetch(_PAGE_HTML, monkeypatch)
    plain = next(li for li in rows if li.parcel_id == "1001870")
    assert plain.raw["henderson_tax"]["case_detail_url"] is None


def test_other_fields_still_parse(monkeypatch):
    rows = _run_fetch(_PAGE_HTML, monkeypatch)
    linked = next(li for li in rows if li.parcel_id == "301249")
    assert linked.owner_name == "CASE, GREGORY P HEIRS"
    assert linked.opening_bid == 777.17
    assert linked.case_number == "25M000267-440"
    assert linked.sale_date is not None and linked.sale_date.isoformat()[:10] == "2026-05-27"
    assert linked.sale_location == "200 N Grove St, Hendersonville, NC 28792"
