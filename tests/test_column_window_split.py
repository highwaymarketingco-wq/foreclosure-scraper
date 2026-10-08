"""Column legal notices: a window with more rows than one 250-row page is split.

The 2026-10-07 extraction audit found one county with 391 rows in the 120-day
window; the single page kept the newest 250 and silently dropped the rest.
The fake server below honours the date filter and the page size, and reports
total_results the way the live API does (page.total_results).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.newspapers import column_legal_notices as m

DAY = 86_400_000
T0 = 1_780_000_000_000


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeColumn:
    def __init__(self, n_rows: int, span_days: int = 120):
        step = span_days * DAY // n_rows
        self.rows = [{"id": f"n{i}-0", "publishedtimestamp": T0 - i * step, "text": ""}
                     for i in range(n_rows)]
        self.posts = 0

    async def post(self, url, json=None, **kw):
        self.posts += 1
        win = next(f["publishedtimestamp"] for f in json["allFilters"] if "publishedtimestamp" in f)
        hits = [r for r in self.rows if win["from"] <= r["publishedtimestamp"] <= win["to"]]
        hits.sort(key=lambda r: -r["publishedtimestamp"])
        page = hits[: json["pageSize"]]
        return _Resp({"results": page,
                      "page": {"current": 1, "total_pages": -(-len(hits) // json["pageSize"]),
                               "total_results": len(hits), "size": json["pageSize"]}})


def test_full_page_window_is_split_until_every_row_is_read():
    srv = _FakeColumn(391)
    got = asyncio.run(m._query(srv, m._NC, "Example", "Notice to Creditors",
                               T0 - 120 * DAY, T0))
    assert len(got) == 391
    assert len({r["id"] for r in got}) == 391
    assert srv.posts <= 7


def test_small_window_costs_one_post():
    srv = _FakeColumn(40)
    got = asyncio.run(m._query(srv, m._NC, "Example", "Notice to Creditors",
                               T0 - 120 * DAY, T0))
    assert len(got) == 40 and srv.posts == 1
