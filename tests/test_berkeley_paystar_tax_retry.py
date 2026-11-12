"""counties_sc.berkeley_paystar_tax._list_all: a transient transport error on the
paginated search POST gets retried, not treated as "the whole roll is empty."

Found 2026-11-07 (gap-sweep): _list_all() pages the Unpaid Real Property search
with a bare `await client.post(...)` inside its `while True:` loop, immediately
followed by `r.raise_for_status()` -- no try/except exists anywhere inside
_list_all itself. The only thing touching it is fetch()'s own single bare
`try: rows = await _list_all(client) except Exception: ... return out` --
crash-containment, not a retry (no second attempt is made). Because `out`
inside _list_all is a purely local accumulator, a transient
httpx.TransportError/timeout on ANY page -- even deep into pagination after
thousands of rows were already fetched -- discards everything accumulated so
far and propagates straight out, zeroing the whole run's result. Because this
source is registered in main.DATELESS_OK_SOURCES (no fallback date window), a
zeroed run cannot self-heal later -- it just silently reports an empty
"healthy" result until someone notices by hand. Same bug shape already fixed
tonight in a Column legal-notice API scraper, spartan_weekly_legals.py, and
the shared arcgis_webmap.query_features().
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import berkeley_paystar_tax as mod


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=self)


class _FlakyClient:
    """Raises on the first N-1 POSTs to the search endpoint, then serves a real
    (empty, terminal -- one page shorter than _PAGE_SIZE) page.
    """

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def post(self, url, json=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp({"data": {"results": []}})


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


@pytest.fixture(autouse=True)
def _skip_facets_probe(monkeypatch):
    """_list_all's first move is _prior_tax_years(client) -- a SEPARATE call this
    fix scoped OUT (it already has its own graceful-fallback try/except, just not
    a retry -- see the investigation this test file's docstring summarizes).
    Stub it so every POST the fake clients below count belongs to the
    pagination loop under test, not the facets probe.
    """
    async def _no_facets(client):
        return None
    monkeypatch.setattr(mod, "_prior_tax_years", _no_facets)


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    client = _FlakyClient(fail_times=2)
    rows = asyncio.run(mod._list_all(client))
    assert client.calls == 3
    assert rows == []


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    client = _FlakyClient(fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(mod._list_all(client))
    assert client.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite retry/hang


def test_a_read_timeout_is_also_retried():
    client = _FlakyClient(fail_times=1, exc=httpx.ReadTimeout("slow"))
    rows = asyncio.run(mod._list_all(client))
    assert client.calls == 2
    assert rows == []


def test_a_real_http_error_status_is_not_retried():
    class _BadStatusClient:
        def __init__(self):
            self.calls = 0

        async def post(self, url, json=None):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    client = _BadStatusClient()
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(mod._list_all(client))
    assert client.calls == 1   # a real bad status is not a transport/timeout error -- unretried
