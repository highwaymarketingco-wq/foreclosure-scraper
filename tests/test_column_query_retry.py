"""Column legal notices (newspapers/column_legal_notices.py): _query_once retries a transient
transport error instead of silently returning zero rows for the whole window.

2026-10-16: found via the sibling scrapers/public_notices/nc_heir_notices.py, which hits the
SAME Column API with the SAME bare `c.post` (no retry) and had every one of its 5 queries fail
with a transient transport error on the only production run it has had so far -- zeroing 973
notices / 90 leads for the entire run. http_client.client() disables the transport's own
retries BY DESIGN (its own docstring: "callers already wrap their own AsyncRetrying"), and
this call never did either.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.newspapers import column_legal_notices as m


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {"results": [], "page": {"total_results": 0}}

    def json(self):
        return self._body

    def raise_for_status(self):
        raise httpx.HTTPStatusError("bad status", request=None, response=self)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """The real backoff is 1-8s per attempt; make the retry tests instant."""
    monkeypatch.setattr(m, "wait_exponential_jitter", lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    calls = {"n": 0}

    class _C:
        async def post(self, *a, **kw):
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ConnectTimeout("boom")
            return _Resp(body={"results": [{"id": "ok", "publishedtimestamp": 1}],
                               "page": {"total_results": 1}})

    items, total, n_raw = asyncio.run(m._query_once(_C(), m._NC, "Example", "Notice to Creditors", 0, 1))
    assert calls["n"] == 3
    assert items == [{"id": "ok", "publishedtimestamp": 1}] and total == 1 and n_raw == 1


def test_a_connect_timeout_that_never_clears_still_returns_empty_not_raise():
    calls = {"n": 0}

    class _C:
        async def post(self, *a, **kw):
            calls["n"] += 1
            raise httpx.ConnectTimeout("always boom")

    items, total, n_raw = asyncio.run(m._query_once(_C(), m._NC, "Example", "Notice to Creditors", 0, 1))
    assert calls["n"] == 3                      # stop_after_attempt(3), then gives up gracefully
    assert (items, total, n_raw) == ([], None, 0)


def test_a_real_404_is_not_retried_and_propagates():
    calls = {"n": 0}

    class _C:
        async def post(self, *a, **kw):
            calls["n"] += 1
            return _Resp(status_code=404)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(m._query_once(_C(), m._NC, "Example", "Notice to Creditors", 0, 1))
    assert calls["n"] == 1                      # a real bad status is not a transport/timeout error
