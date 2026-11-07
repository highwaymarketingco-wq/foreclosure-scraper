"""henderson_code_violations._fetch_attachments: a transient transport error on the
queryAttachments call gets retried, not treated as "this chunk has no photos."

Found 2026-11-07 (sourced/not-built gap sweep): this file has three real network
call sites. Two of them -- fetch()'s open-case query and fetch_history()'s history
query -- go through arcgis_webmap.query_features / query_attributes, which already
wrap their own AsyncRetrying (fixed 2026-10-16, see
test_arcgis_webmap_query_features_retry.py). The third, _fetch_attachments's
queryAttachments call, bypasses arcgis_webmap entirely and hits the bare
http_client.client() directly -- and http_client.client() sets retries=0 on its
transport ("callers already wrap their own AsyncRetrying"), so this call had zero
retry cushioning of its own. The only wrapper present was a bare
``try/except Exception`` that, on ANY exception (and on any non-200 status), just
moved on to the NEXT chunk -- never re-attempting the SAME chunk's request. With
expected_min_count=25 and _ATTACH_CHUNK=150, a typical run's open-case volume
plausibly fits inside a single chunk, so one transient blip (a connection reset, a
timeout) could zero every case photo for that run with zero retry ever attempted.
Same root-cause class already fixed tonight in this repo for the Column
legal-notice API scraper, spartan_weekly_legals.py, and
arcgis_webmap.query_features() itself.

_fetch_attachments's own contract (its docstring) is "Never raises; a
failed/partial chunk just yields no photos for those ids" -- the pre-existing
outer try/except that makes that true is untouched by this fix. What the fix adds
is retry CUSHIONING inside that: a permanently-flaky chunk now gives up only after
a bounded number of attempts (stop_after_attempt(3)) instead of never retrying at
all (the bug this fixes).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_nc import henderson_code_violations as mod


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FlakyHttp:
    """Raises on the first N-1 calls, then serves a real (terminal) attachments page."""

    def __init__(self, fail_times: int, exc=None, payload=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.payload = payload if payload is not None else {"attachmentGroups": []}
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(self.payload)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Same trick the reference retry test uses: swap in a near-zero backoff so
    the retry-then-succeed / exhausted-budget tests run instantly instead of
    waiting out the real exponential-jitter schedule."""
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# --------------------------------------------------------------------------- #
# (a) transient transport/timeout errors are retried, then succeed
# --------------------------------------------------------------------------- #

def test_a_transient_connect_timeout_is_retried_and_then_succeeds():
    payload = {"attachmentGroups": [
        {"parentObjectId": 1, "attachmentInfos": [
            {"id": 500, "contentType": "image/jpeg", "name": "a.jpg"}]}]}
    http = _FlakyHttp(fail_times=2, payload=payload)
    out = asyncio.run(mod._fetch_attachments(http, [1]))
    assert http.calls == 3
    assert out == {1: [f"{mod.LAYER}/1/attachments/500"]}


def test_a_read_timeout_is_also_retried():
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    out = asyncio.run(mod._fetch_attachments(http, [1]))
    assert http.calls == 2
    assert out == {}   # terminal page in this test carries no attachmentGroups


# --------------------------------------------------------------------------- #
# (b) a transient error that never clears stops after the retry budget --
#     bounded, not an infinite hang -- and still never raises out of the
#     function (its documented, pre-existing, unchanged contract).
# --------------------------------------------------------------------------- #

def test_a_connect_timeout_that_never_clears_stops_after_the_retry_budget_not_an_infinite_hang():
    http = _FlakyHttp(fail_times=99)
    out = asyncio.run(mod._fetch_attachments(http, [1]))
    assert http.calls == 3     # stop_after_attempt(3), then gives up -- not unbounded
    assert out == {}           # swallowed by the unchanged outer catch, same as before the fix


def test_a_timeout_that_never_clears_costs_only_its_own_chunk_not_the_whole_run():
    """Two chunks (300 ids / _ATTACH_CHUNK=150). The first chunk is permanently
    flaky and exhausts its retry budget; the second chunk is clean. The first
    chunk's exhausted retries must not block or consume the second chunk's own
    independent attempt."""
    class _PerChunkHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            params_ids = params["objectIds"]
            if params_ids.startswith("1,"):          # chunk 1 (ids 1..150): always flaky
                raise httpx.ConnectTimeout("boom")
            return _FakeResp({"attachmentGroups": [     # chunk 2 (ids 151..300): clean
                {"parentObjectId": 151, "attachmentInfos": [
                    {"id": 9, "contentType": "image/jpeg"}]}]})

    ids = list(range(1, 301))
    http = _PerChunkHttp()
    out = asyncio.run(mod._fetch_attachments(http, ids))
    assert http.calls == 4     # chunk 1: 3 exhausted attempts; chunk 2: 1 clean attempt
    assert out == {151: [f"{mod.LAYER}/151/attachments/9"]}


# --------------------------------------------------------------------------- #
# (c) a real non-transport HTTP error status is NOT retried
# --------------------------------------------------------------------------- #

def test_a_real_http_error_status_is_not_retried():
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    http = _BadStatusHttp()
    out = asyncio.run(mod._fetch_attachments(http, [1]))
    assert http.calls == 1     # a real bad status is not a transport/timeout error
    assert out == {}
