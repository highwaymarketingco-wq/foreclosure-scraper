"""CourtListener adversary: a failed search page is retried, not the end of the search.

9 of the 20 (court, phrase) searches of the 2026-10-08 gated run ended on a bare
exception (empty error text) after at most one page.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx

from foreclosure_scraper.scrapers.national import courtlistener_adversary as ca


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FlakyClient:
    """First call raises a bare ReadTimeout, then serves one page."""

    def __init__(self):
        self.calls = 0

    async def get(self, url, **kw):
        self.calls += 1
        if self.calls == 1:
            raise httpx.ReadTimeout("")
        return _Resp({"results": [{"docketNumber": "26-00001", "caseName": "In re Sample"}],
                      "next": None})


def test_search_retries_a_timed_out_page():
    c = _FlakyClient()

    async def _no_sleep(*a, **k):
        return None

    with patch.object(ca.asyncio, "sleep", new=_no_sleep):
        rows = asyncio.run(ca._search(c, "tok", "scb", "relief from stay"))
    assert c.calls == 2
    assert [r["docketNumber"] for r in rows] == ["26-00001"]
