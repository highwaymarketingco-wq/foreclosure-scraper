"""cleveland_tax.ClevelandTaxForeclosure.fetch: a transient transport error on the
page fetch gets retried, not treated as "the whole scrape failed."

Found 2026-10-17 (gap-sweep): this file makes exactly ONE network call for its
entire scrape -- `r = await c.get(URL, headers=HEADERS)` inside
`async with client(timeout=20.0) as c:` -- and it had zero retry cushioning, the
same root-cause shape already fixed the same week for the Column legal-notice API
scraper, spartan_weekly_legals.py, and arcgis_webmap.query_features(). http_client's
own client() docstring says every caller must wrap its own retries; this one never
did. Because the page's HTML feeds BOTH the Ninja-Tables grid parser and the inline
"Parcel / File #" parser, a single connection reset or timeout here permanently
zeroes this source's whole output for the run -- and since this scraper carries no
fallback date window, a zeroed run can't self-heal later; it just silently reports
an empty/healthy result.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import cleveland_tax as M

PAGE = (
    '<html><body>'
    '<table><tbody><tr class="ninja_table_row">'
    '<td class="ninja_clmn_nm_county">Cleveland</td>'
    '<td class="ninja_clmn_nm_address">124 Galilee Church Rd, Kings Mountain</td>'
    '<td class="ninja_clmn_nm_parcel">12811</td>'
    '<td class="ninja_clmn_nm_saledatetime">6/25/2026 11:00:00 AM</td>'
    '<td class="ninja_clmn_nm_openingbid">$20,100.00</td>'
    '<td class="ninja_clmn_nm_currentbid">&nbsp;</td>'
    '<td class="ninja_clmn_nm_closedate">7/6/2026</td>'
    '<td class="ninja_clmn_nm_propertytype">Residential Home</td>'
    '<td class="ninja_clmn_nm_courtfile">25CV003450-220</td>'
    '<td class="ninja_clmn_nm_ourfile">24491</td>'
    '<td class="ninja_clmn_nm_salestatus">&nbsp;</td>'
    '</tr></tbody></table>'
    '</body></html>'
)


def _fake_client(get_handler):
    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = get_handler
        yield stub
    return _cm


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(M, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectTimeout("boom")
        return MagicMock(status_code=200, text=PAGE)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.ClevelandTaxForeclosure().fetch())
    assert calls["n"] == 3
    assert len(list(rows)) == 1


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, **kw):
        calls["n"] += 1
        raise httpx.ConnectTimeout("always boom")

    monkeypatch.setattr(M, "client", _fake_client(get))
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(M.ClevelandTaxForeclosure().fetch())
    assert calls["n"] == 3   # stop_after_attempt(3), then gives up


def test_a_read_timeout_is_also_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, **kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return MagicMock(status_code=200, text=PAGE)

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.ClevelandTaxForeclosure().fetch())
    assert calls["n"] == 2
    assert len(list(rows)) == 1


def test_a_real_bad_status_is_not_retried(monkeypatch):
    calls = {"n": 0}

    async def get(url, headers=None, **kw):
        calls["n"] += 1
        return MagicMock(status_code=503, text="")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.ClevelandTaxForeclosure().fetch())
    assert calls["n"] == 1   # a real bad status is not a transport/timeout error
    assert rows == []
