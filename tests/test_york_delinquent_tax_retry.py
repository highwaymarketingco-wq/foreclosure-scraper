"""york_delinquent_tax.YorkDelinquentTax.fetch: a transient transport error on
its one ArcGIS query call gets retried, not treated as "the whole scrape failed."

This scraper makes exactly one HTTP request per run in the normal case
(page_size=2000 against ~853 total records, so the pagination loop body runs
once) and had zero retry cushioning on that call -- the same gap already fixed
in arcgis_webmap.query_features() and its callers. A single transient blip
would otherwise permanently zero the whole ~850-listing scrape for the run,
reported as a healthy empty result rather than a visible failure.

Unlike arcgis_webmap.query_features (an async client awaited with
``http.get(...)``), this scraper's call is synchronous (``httpx.Client()`` /
``client.get()``, no ``await``) inside an ``async def fetch()``. The
``AsyncRetrying`` / ``with attempt:`` pattern wraps it the same way regardless,
so the fakes below mirror the real scraper's own sync-client-as-context-manager
shape (see ``test_york_delinquent_tax.py``'s ``_FakeHttpxClient``), not the
async ``http.get``/``http.post`` shape used in the arcgis_webmap tests.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc.york_delinquent_tax import YorkDelinquentTax


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FlakyHttpxClient:
    """Sync stand-in for ``httpx.Client(timeout=...)`` used as a context manager,
    matching the scraper's own call shape (``with httpx.Client(...) as client:
    ... client.get(...)``). Raises ``exc`` on the first ``fail_times`` calls to
    ``.get()``, then returns a real terminal (empty, non-paginating) page.
    """

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(200, {"features": [], "exceededTransferLimit": False})


class _BadStatusHttpxClient:
    """Always returns a real (non-exception) bad HTTP status -- the scraper's
    own ``status_code != 200`` branch must still handle this, and it must not
    be retried: a bad status is not a transport/timeout error."""

    def __init__(self, status_code=503):
        self.status_code = status_code
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        self.calls += 1
        return _FakeResp(self.status_code, {}, text="Service Unavailable")


def _patch_client(monkeypatch, client):
    import foreclosure_scraper.scrapers.counties_sc.york_delinquent_tax as m
    monkeypatch.setattr(m.httpx, "Client", lambda timeout=None: client)
    return m


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    import foreclosure_scraper.scrapers.counties_sc.york_delinquent_tax as m
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    client = _FlakyHttpxClient(fail_times=2)
    _patch_client(monkeypatch, client)

    rows = list(asyncio.run(YorkDelinquentTax().fetch()))
    assert client.calls == 3
    assert rows == []


def test_a_connect_timeout_that_never_clears_still_raises_not_hangs(monkeypatch):
    client = _FlakyHttpxClient(fail_times=99)
    _patch_client(monkeypatch, client)

    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(YorkDelinquentTax().fetch())
    assert client.calls == 3  # stop_after_attempt(3), then gives up


def test_a_read_timeout_is_also_retried(monkeypatch):
    client = _FlakyHttpxClient(fail_times=1, exc=httpx.ReadTimeout("slow"))
    _patch_client(monkeypatch, client)

    rows = list(asyncio.run(YorkDelinquentTax().fetch()))
    assert client.calls == 2
    assert rows == []


def test_a_real_http_error_status_is_not_retried(monkeypatch):
    client = _BadStatusHttpxClient(status_code=503)
    _patch_client(monkeypatch, client)

    rows = list(asyncio.run(YorkDelinquentTax().fetch()))
    assert rows == []
    assert client.calls == 1  # a real bad status is not a transport/timeout error
