"""publicnoticesc_estates: a failed preset is retried once, and a run that read nothing because
every attempt failed says why instead of reporting a clean ZERO_RESULT.

Source-completeness audit 2026-10-08: the VM's first run returned 0 rows in 35 s as ZERO_RESULT
with nothing in the log, while the same code on the Mac read 100 previews and named 9 estates.
These tests fail on that code. Made-up names; grid markup in the shape _press_assoc.parse_grid reads.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.base_scraper import OUTCOME_ERROR
from foreclosure_scraper.scrapers.public_notices import publicnoticesc_estates as est


def _row(nid: str, text: str, county: str = "Jasper") -> str:
    return (f'<table class="nested"><tr><td><input onclick="location.href=\'Details.aspx?SID=abc&ID={nid}\'"></td>'
            f'<td><div class="left"><strong>Test Gazette</strong><br>Thursday, October 1, 2026</div>'
            f'<div class="right" style="display:none">City: Ridgeland<br>County: {county}</div></td></tr>'
            f'<tr><td colspan="3">{text}... click \'view\' to open the full text.</td></tr></table>')


HEAD = "<html><input type='hidden' name='__VIEWSTATE' value='v'/>"
PAGES = {
    "30": HEAD + _row("1", "STATE OF SOUTH CAROLINA COUNTY OF: JASPER IN THE MATTER OF: ORVEL QUIMBY TANDRY "
                           "(DECEASED) NOTICE TO CREDITORS CASE NUMBER: 2026-ES-27-00206") + "</html>",
    "23": HEAD + _row("2", "STATE OF SOUTH CAROLINA COUNTY OF: AIKEN IN THE MATTER OF: PELL ASTER WINTHROPE "
                           "(DECEASED) PROBATE NOTICE CASE NUMBER: 2026-ES-02-00999", county="Aiken") + "</html>",
}


class Fake:
    """Opening a session fails the first `fail_opens` times, then the portal answers."""

    def __init__(self, fail_opens: int):
        self.fail_opens = fail_opens
        self.opens = 0
        self.preset = None
        self.walled = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def get_with_url(self, url):
        self.opens += 1
        if self.opens <= self.fail_opens:
            raise RuntimeError("HTTP 503 from the portal")
        return HEAD + "</html>", "https://www.scpublicnotices.com/(S(x))/Search.aspx"

    async def post(self, url, data):
        p = data.get(est.PRE + "ddlPopularSearches")
        if p:
            self.preset = p
        return PAGES[self.preset]


def _run(monkeypatch, fail_opens: int):
    fake = Fake(fail_opens)
    monkeypatch.setattr(est, "PoliteFetcher", lambda: fake)
    monkeypatch.setattr(est, "_RETRY_PAUSE_S", 0.0, raising=False)
    s = est.PublicNoticeSCEstates()
    rows = asyncio.run(s.safe_run())
    return s, rows


def test_a_preset_that_fails_once_is_retried(monkeypatch):
    s, rows = _run(monkeypatch, fail_opens=1)
    assert sorted(li.county for li in rows) == ["Aiken", "Jasper"]


def test_a_run_where_every_attempt_failed_is_not_a_clean_zero(monkeypatch):
    s, rows = _run(monkeypatch, fail_opens=99)
    assert rows == []
    assert s.last_outcome == OUTCOME_ERROR
    assert "503" in s.last_reason
