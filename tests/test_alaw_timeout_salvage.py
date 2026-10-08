"""ALAW: a hang on one page must not throw away the other page's parsed rows.

Audit 2026-10-08: the gated VM run hit the 180 s soft timeout with 0 rows (3 runs at 0 after
~26 per run). Each of the two pages (NC, SC) could hold the render for twice its budget, and a
timeout returned nothing even when the first page had parsed. Fixture cells are invented.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_PARTIAL
from foreclosure_scraper.scrapers.law_firms import alaw


def _cell(col: int, row: int, text: str) -> str:
    return '\\"Col\\":%d,\\"Row\\":%d,\\"Text\\":\\"%s\\"' % (col, row, text)


_HEAD = ["File Number", "Case Status", "Address", "City", "Zip", "County", "Bid Amount",
         "Current Sale Date", "Court Case Number"]
_ROW1 = ["F-0001", "FORECLOSURE", "100 Example Lane", "Testville", "28000", "NC - Gaston",
         "$1,000.00", "11/12/2026", "26SP000001-000"]
_ROW2 = ["F-0002", "FORECLOSURE", "200 Sample Road", "Mocktown", "28001", "NC - Cleveland",
         "", "11/19/2026", "26SP000002-000"]
_WAC = ",".join(
    [_cell(c, 0, t) for c, t in enumerate(_HEAD)]
    + [_cell(c, 1, t) for c, t in enumerate(_ROW1)]
    + [_cell(c, 2, t) for c, t in enumerate(_ROW2)]
)
_PAGE = ('<iframe data-lazy-src="https://albertellilaw.sharepoint.com/:x:/s/FCSales/'
         'TOKEN?e=X&amp;action=embedview"></iframe>')


def test_fixture_parses():
    rows = alaw.parse_wac_cells(_WAC)
    assert [r.county for r in rows] == ["Gaston", "Cleveland"]


def test_second_page_hang_keeps_first_page_rows(monkeypatch):
    calls = {"n": 0}

    async def _get_text(url, timeout=45.0):
        return _PAGE

    async def _render(embed_url):
        calls["n"] += 1
        if calls["n"] == 1:
            return _WAC
        await asyncio.sleep(60)  # the second page never delivers its bootstrap
        return ""

    monkeypatch.setattr(alaw, "get_text", _get_text)
    monkeypatch.setattr(alaw, "_render_capture", _render)
    s = alaw.Alaw()
    s.timeout_s = 0.5
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome == OUTCOME_PARTIAL
    assert len(rows) == 2
