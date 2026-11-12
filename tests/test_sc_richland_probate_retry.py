"""counties_sc.sc_richland_probate._fetch_detail: a transient transport/timeout error on the
per-case PR/attorney detail GET gets retried, not treated as "this case has no contact info."

Found 2026-11-07 (gap-sweep): _fetch_detail's own GET (Detail.aspx, the Personal
Representative/Attorney contact page for one kept probate case) was a single bare attempt --
``try: r = await client.get(...); r.raise_for_status() except httpx.HTTPError: return {}`` --
with no loop, no AsyncRetrying, no decorator. ``_search()`` above it in this same module
already has its own manual retry loop for the load-balanced-server viewstate-MAC race (module
docstring), but this second, separate call site had zero retry cushioning. A single connection
reset or timeout here used to permanently drop that one case's PR/attorney enrichment for the
run -- the probate-notice lead itself survives regardless (fetch()'s own try/except around
_fetch_detail already treats a missing detail as non-fatal), but the degraded-yet-"successful"
run still can't self-heal since this source carries no fallback date window
(main.DATELESS_OK_SOURCES). Same bug class already fixed the same night for the Column
legal-notice API scraper, spartan_weekly_legals.py, and arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import sc_richland_probate as M

CASE_NO = "2026-ES40-00110"
LAST = "Lucas"
FIRST = "Marjan"

# Header-row-only tables: a genuinely parseable, "no party on file" terminal response --
# _parse_party_table requires >= 2 <tr> (header + one data row), so this yields {"pr": None,
# "attorney": None} rather than inventing a party, exactly like a real empty Detail.aspx page.
_DETAIL_HTML = """
<table id="dlPR"><tr><td>header</td></tr></table>
<table id="dlAT"><tr><td>header</td></tr></table>
"""


class _FakeResp:
    def __init__(self, text=_DETAIL_HTML, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=None, response=self)


class _FakeClient:
    """Minimal stand-in for httpx.AsyncClient -- only the one method _fetch_detail calls."""

    def __init__(self, get):
        self.get = get


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """The real backoff is 1-8s per attempt; make the retry tests instant."""
    monkeypatch.setattr(M, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    calls = {"n": 0}

    async def get(url, params=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return _FakeResp()

    detail = asyncio.run(M._fetch_detail(_FakeClient(get), CASE_NO, LAST, FIRST))
    assert calls["n"] == 3
    assert detail == {"pr": None, "attorney": None}


def test_a_connect_timeout_that_never_clears_still_degrades_cleanly_not_hangs():
    calls = {"n": 0}

    async def get(url, params=None):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    detail = asyncio.run(M._fetch_detail(_FakeClient(get), CASE_NO, LAST, FIRST))
    assert calls["n"] == 3   # stop_after_attempt(3), then gives up gracefully (no hang)
    assert detail == {}      # _fetch_detail's own contract: never raises, {} on any failure


def test_a_read_timeout_is_also_retried():
    calls = {"n": 0}

    async def get(url, params=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return _FakeResp()

    detail = asyncio.run(M._fetch_detail(_FakeClient(get), CASE_NO, LAST, FIRST))
    assert calls["n"] == 2
    assert detail == {"pr": None, "attorney": None}


def test_a_real_bad_status_is_not_retried():
    calls = {"n": 0}

    async def get(url, params=None):
        calls["n"] += 1
        return _FakeResp(status_code=503)

    detail = asyncio.run(M._fetch_detail(_FakeClient(get), CASE_NO, LAST, FIRST))
    assert calls["n"] == 1   # a real bad HTTP status is not a transport/timeout error
    assert detail == {}
