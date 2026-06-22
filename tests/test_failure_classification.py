"""safe_run classifies WHY a source produced nothing: OK / ZERO_RESULT /
TIMEOUT / BLOCKED / ERROR — so a 0-count is never ambiguous to the owner."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from foreclosure_scraper.base_scraper import BaseScraper
from foreclosure_scraper.models import Listing, ListingType


def _mk(fetch_impl, **attrs):
    class _S(BaseScraper):
        slug = attrs.get("slug", "test.s")
        name = "t"
        timeout_s = attrs.get("timeout_s", 5.0)
        async def fetch(self):
            return await fetch_impl()
    return _S()


def _run(s):
    return asyncio.run(s.safe_run())


def test_ok_when_rows():
    async def f():
        return [Listing(source="t", source_url="u", listing_type=ListingType.REO,
                        state="NC", county="Gaston")]
    s = _mk(f)
    out = _run(s)
    assert len(out) == 1 and s.last_outcome == "OK"


def test_zero_result_when_empty():
    async def f():
        return []
    s = _mk(f)
    _run(s)
    assert s.last_outcome == "ZERO_RESULT" and "0 rows" in s.last_reason


def test_blocked_on_403():
    async def f():
        req = httpx.Request("GET", "https://x.example")
        resp = httpx.Response(403, request=req)
        raise httpx.HTTPStatusError("forbidden", request=req, response=resp)
    s = _mk(f)
    _run(s)
    assert s.last_outcome == "BLOCKED" and "403" in s.last_reason


def test_blocked_on_429_rate_limit():
    async def f():
        req = httpx.Request("GET", "https://x.example")
        raise httpx.HTTPStatusError("too many", request=req, response=httpx.Response(429, request=req))
    s = _mk(f)
    _run(s)
    assert s.last_outcome == "BLOCKED" and "rate-limited" in s.last_reason


def test_blocked_on_connect_error():
    async def f():
        raise httpx.ConnectError("connection refused")
    s = _mk(f)
    _run(s)
    assert s.last_outcome == "BLOCKED" and "ConnectError" in s.last_reason


def test_error_on_code_bug():
    async def f():
        raise ValueError("bad parse at row 3")
    s = _mk(f)
    _run(s)
    assert s.last_outcome == "ERROR"
    assert "ValueError" in s.last_reason and "bad parse" in s.last_reason


def test_timeout():
    async def f():
        await asyncio.sleep(0.2)
        return []
    s = _mk(f, timeout_s=0.01)
    _run(s)
    assert s.last_outcome == "TIMEOUT"


def test_swallowed_block_promoted_to_blocked():
    # A scraper that catches its own HTTP error and returns [] is still flagged
    # BLOCKED because the shared transport recorded the block in the run's holder.
    from foreclosure_scraper.http_client import _block_holder

    async def f():
        h = _block_holder.get()        # safe_run set a fresh list before fetch
        if h is not None:
            h.append((403, "HTTP 403 (blocked/forbidden) from courts.example"))
        return []   # swallowed the error
    s = _mk(f)
    _run(s)
    assert s.last_outcome == "BLOCKED"
    assert "403" in s.last_reason and "swallowed" in s.last_reason


def test_swallowed_block_survives_child_task():
    # The Pass-3 bug: the block append happens in a CHILD task (asyncio.gather);
    # the shared-list holder must still surface it to safe_run in the parent.
    from foreclosure_scraper.http_client import _block_holder

    async def f():
        async def child():
            h = _block_holder.get()
            if h is not None:
                h.append((429, "HTTP 429 (rate-limited) from gis.example"))
            return []
        await asyncio.gather(child())   # fetch inside a child task
        return []
    s = _mk(f)
    _run(s)
    assert s.last_outcome == "BLOCKED" and "429" in s.last_reason


def test_clean_zero_not_promoted_without_block():
    async def f():
        return []
    s = _mk(f)
    _run(s)
    assert s.last_outcome == "ZERO_RESULT"   # no block signal -> stays ZERO


def test_500_is_blocked_possible_waf():
    async def f():
        req = httpx.Request("GET", "https://x.example")
        raise httpx.HTTPStatusError("err", request=req, response=httpx.Response(503, request=req))
    s = _mk(f)
    _run(s)
    assert s.last_outcome == "BLOCKED" and "503" in s.last_reason
