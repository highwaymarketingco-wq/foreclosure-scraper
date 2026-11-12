"""spartan_weekly_legals: a soft timeout during detail enrichment ships the notices already listed.

Source-completeness audit 2026-10-08: the VM's run took 184 s of the 240 s timeout, and the
rows lived only in a local list until the end, so a slower day would have shipped none of them.
This test fails on that code. Invented notice rows in the site's list markup.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

from foreclosure_scraper.base_scraper import OUTCOME_PARTIAL
from foreclosure_scraper.scrapers.counties_sc import spartan_weekly_legals as M

PAGE = (
    '<div class="article col"><h6>Master In Equity</h6>'
    '<h4><a href="/legal-notices/12-testa-placeholder-rd">12 Testa Placeholder Rd</a></h4>'
    '<p> Case #:2026CP4200001<br> October 1, 2026 </p></div>'
    '<div class="article col"><h6>Probate Court</h6>'
    '<h4><a href="/legal-notices/estate-of-morrow-example">Estate of Morrow Example</a></h4>'
    '<p> Case #:2026CP4200002<br> October 2, 2026 </p></div>'
)


def _fake_client(get_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        yield stub
    return _cm


def test_a_timeout_during_enrichment_ships_the_listed_notices(monkeypatch):
    async def get(url, **kw):
        if "/legal-notices/?page=1" in url:
            return MagicMock(status_code=200, text=PAGE)
        if "/legal-notices/?page=" in url:
            return MagicMock(status_code=404, text="")
        await asyncio.sleep(3600)          # a detail page that never answers

    monkeypatch.setattr(M, "client", _fake_client(get))
    s = M.SpartanWeeklyLegals()
    s.timeout_s = 0.5
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome == OUTCOME_PARTIAL
    assert len(rows) == 2
