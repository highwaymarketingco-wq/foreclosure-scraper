"""Anderson MIE: every results PDF in the 180-day window is read once, and the sale hour is kept.

Audit 2026-10-08 (the 10/7 extraction audit's open item "results/deficiency PDFs, real sale
time"), measured on the live page: the August results were posted as
"...-Sale-List-Results.pdf", which neither the selector nor RESULTS_HREF_RE admitted; a cap of 6
read 5 distinct results PDFs of the 9 in the window (one twice); and every PDF's header states
"SALES ARE HELD ... 11:00 AM" while sale_date stayed at midnight. Fixture text is invented.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from foreclosure_scraper.scrapers.counties_sc import anderson_master_in_equity as A

_MONTH_NAMES = {v: k.capitalize() for k, v in A.MONTHS.items()}
_HEADER = ("FORECLOSURE SALE LIST SALES ARE HELD AT THE ANDERSON COUNTY COURTHOUSE, THIRD FLOOR, "
           "COURTROOM #2, 11:00 AM. FOR PROPERTY INFORMATION CHECK THE CASE FILE.\n")


def _stem(d: datetime) -> str:
    return f"{_MONTH_NAMES[d.month]}-{d.day}-{d.year}"


def _row(n: int, price: bool) -> str:
    tail = " To Third Party $100,000.00" if price else ""
    return (f"{n}. 26-{1000 + n} B&S Example Bank v. Sample Owner{n}, et al. Lot {n} PB1@{n} "
            f"{100 + n} Example Lane{tail}\n")


def _build(now: datetime):
    upcoming = now + timedelta(days=20)
    results_dates = [now - timedelta(days=d) for d in (5, 30, 33, 60, 90, 120, 123, 150, 152)]
    links, texts = [], {}
    base = "https://www.andersoncountysc.org/wp-content/uploads/2026/01/"
    sl = base + f"{_stem(upcoming)}-Sale-List.pdf"
    links.append(sl)
    texts[sl] = _HEADER + _row(1, False) + _row(2, False)
    for i, d in enumerate(results_dates):
        kind = ("Sale-List-Results" if i == 3 else
                "Deficiency-Sale-Results" if i % 2 else "Sale-Results")
        u = base + f"{_stem(d)}-{kind}.pdf"
        links.append(u)
        texts[u] = _HEADER + _row(10 + i, True)
    page = "<html><body>" + "".join(f'<a href="{u}">x</a>' for u in links) + "</body></html>"
    return page, texts, results_dates


def _run(monkeypatch):
    now = datetime.utcnow()
    page, texts, results_dates = _build(now)
    fetched: list[str] = []

    class _Resp:
        def __init__(self, body):
            self.status_code = 200
            self.text = body if isinstance(body, str) else ""
            self.content = body.encode() if isinstance(body, str) else body

    class _Client:
        async def get(self, url, **_kw):
            if url == A.PAGE_URL:
                return _Resp(page)
            fetched.append(url)
            return _Resp(url.encode())

    @asynccontextmanager
    async def _client(**_kw):
        yield _Client()

    monkeypatch.setattr(A, "client", _client)
    monkeypatch.setattr(A, "_extract_pdf_text", lambda data: texts.get(data.decode(), ""))
    out = list(asyncio.run(A.AndersonMasterInEquity().fetch()))
    return out, fetched, results_dates


def test_every_results_pdf_in_window_read_once(monkeypatch):
    out, fetched, results_dates = _run(monkeypatch)
    results_fetched = [u for u in fetched if "-Results" in u]
    assert len(results_fetched) == len(set(results_fetched)) == len(results_dates) == 9
    assert any("Sale-List-Results" in u for u in results_fetched)
    priced = [li for li in out if (li.raw or {}).get("actual_sold_price")]
    assert len(priced) == 9


def test_sale_list_rows_carry_the_stated_hour(monkeypatch):
    out, _fetched, _ = _run(monkeypatch)
    upcoming = [li for li in out if "anderson_mie" in (li.raw or {})]
    assert len(upcoming) == 2
    assert all(li.sale_date.hour == 11 and li.sale_date.minute == 0 for li in upcoming)


def test_at_sale_time_keeps_date_when_no_hour_stated():
    d = datetime(2026, 11, 2)
    assert A._at_sale_time(d, "no header here") == d
    assert A._at_sale_time(d, "SALES ARE HELD AT THE COURTHOUSE, 2:30 PM.").hour == 14
