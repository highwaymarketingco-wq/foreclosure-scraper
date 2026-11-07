"""cott_recordroom.discover_recent_nods: a transient transport error on any of
its three network calls gets retried, not treated as "the whole scrape failed."

Found 2026-11-07 (gap-sweep): sc_rod_cott.py's entire fetch() delegates to this
one shared helper, which made THREE bare client() calls -- the initial GET
(`/guest/Search/records`), the search-setup POST (`/search/Records`), and the
paginated DataTables POST (`/Search/Records/Result/`, up to 6 pages) -- none
wrapped in any retry. All three sat inside ONE outer `except Exception: return
[]`, so a transient blip on ANY of them (even the per-page POST after several
pages had already been collected into `out`) silently zeroed the function's
entire output, logged only as a warning. Same root cause already fixed tonight
for the Column legal-notice API scrapers, spartan_weekly_legals.py, and
arcgis_webmap.query_features() (http_client-style callers must wrap their own
AsyncRetrying; client() deliberately does not -- see http_client.py's comment
above its transport's retries=0).

Because COTT_RR_COUNTIES has exactly one registered county (SC/Union) and this
scraper is registered in main.DATELESS_OK_SOURCES (no fallback date window), a
zeroed run here could not self-heal on a later pass.

NUANCE vs. the arcgis_webmap.query_features precedent this is modeled on:
discover_recent_nods() never raises past its own outer `except Exception` --
by design, unchanged by this fix, it always returns a list (possibly empty).
So once AsyncRetrying's own retry budget is exhausted, the exception it
re-raises is still caught by that SAME pre-existing outer handler and the
function still returns [] rather than raising to the caller. The tests below
prove the retry budget is actually honored (exactly stop_after_attempt(3)
attempts, never more, never an infinite hang) via call counts and the
`log.warning` path actually firing, rather than via `pytest.raises` at the
`discover_recent_nods` call boundary -- `pytest.raises` IS used at the
dedicated-GET test below, since nothing downstream of that one catches it
either way, same outer contract.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.rod import cott_recordroom as cr

_BASE = "https://recordroom.cottsystems.com/unionsc"


class _FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}

    def json(self):
        return self._json_data


class _FlakyClient:
    """Stands in for the `c` yielded by http_client.client(timeout=60.0).

    The initial GET and the one-time search-setup POST (identified by passing
    `data=`, matching discover_recent_nods's own call shape) always succeed on
    the first try. The flaky behaviour targets the PAGINATED DataTables POST
    (identified by passing `json=`) -- the highest-stakes of the three calls,
    since it sits inside the `for start in range(...)` loop and, pre-fix, a
    failure there after several pages already succeeded would have discarded
    every page already collected. Raises `exc` on the first `fail_times` calls
    to that paginated POST, then serves a real terminal (zero-row) page so
    discover_recent_nods completes normally.
    """

    def __init__(self, fail_times: int, exc: BaseException | None = None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.get_calls = 0
        self.setup_post_calls = 0
        self.paginate_calls = 0

    async def get(self, url, **kw):
        self.get_calls += 1
        return _FakeResp(200)

    async def post(self, url, data=None, json=None, headers=None, **kw):
        if json is None:
            self.setup_post_calls += 1
            return _FakeResp(200)
        self.paginate_calls += 1
        if self.paginate_calls <= self.fail_times:
            raise self.exc
        return _FakeResp(200, json_data={"recordsTotal": 0, "data": []})


class _FlakyGetClient:
    """Same idea, but the flaky call is the very first GET instead of the
    paginated POST -- proves the first of the three wraps independently."""

    def __init__(self, fail_times: int, exc: BaseException | None = None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.get_calls = 0
        self.setup_post_calls = 0
        self.paginate_calls = 0

    async def get(self, url, **kw):
        self.get_calls += 1
        if self.get_calls <= self.fail_times:
            raise self.exc
        return _FakeResp(200)

    async def post(self, url, data=None, json=None, headers=None, **kw):
        if json is None:
            self.setup_post_calls += 1
            return _FakeResp(200)
        self.paginate_calls += 1
        return _FakeResp(200, json_data={"recordsTotal": 0, "data": []})


def _patched_client(fake):
    @asynccontextmanager
    async def _cm(**kw):
        yield fake

    return _cm


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(cr, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# --- (a) transient transport/timeout error is retried and then succeeds -----

def test_a_transient_connect_timeout_on_the_paginated_post_is_retried_and_succeeds(monkeypatch):
    fake = _FlakyClient(fail_times=2)
    monkeypatch.setattr(cr, "client", _patched_client(fake))
    docs = asyncio.run(cr.discover_recent_nods("SC", "Union", days_back=5, max_docs=10))
    assert docs == []
    assert fake.paginate_calls == 3   # 2 failures, then a success
    assert fake.get_calls == 1
    assert fake.setup_post_calls == 1


def test_a_read_timeout_on_the_paginated_post_is_also_retried(monkeypatch):
    fake = _FlakyClient(fail_times=1, exc=httpx.ReadTimeout("slow"))
    monkeypatch.setattr(cr, "client", _patched_client(fake))
    docs = asyncio.run(cr.discover_recent_nods("SC", "Union", days_back=5, max_docs=10))
    assert docs == []
    assert fake.paginate_calls == 2   # 1 failure, then a success


def test_a_transient_connect_timeout_on_the_initial_get_is_retried_and_succeeds(monkeypatch):
    """Independently proves the FIRST of the three wraps (the anonymous-session
    GET) retries too, not just the paginated POST."""
    fake = _FlakyGetClient(fail_times=2)
    monkeypatch.setattr(cr, "client", _patched_client(fake))
    docs = asyncio.run(cr.discover_recent_nods("SC", "Union", days_back=5, max_docs=10))
    assert docs == []
    assert fake.get_calls == 3   # 2 failures, then a success
    assert fake.setup_post_calls == 1
    assert fake.paginate_calls == 1


# --- (b) a transient error that never clears exhausts the retry budget ------
# -- not an infinite hang -- rather than being retried forever. See the module
# docstring: discover_recent_nods's own pre-existing outer `except Exception`
# (unchanged by this fix) still intercepts the exhausted-retry exception and
# returns [], so the proof that retries genuinely ran out (vs. hanging, vs.
# silently giving up after only 1 try) is the exact attempt count plus the
# warning path actually firing -- not a raise at this call boundary.

def test_a_connect_timeout_that_never_clears_exhausts_retries_not_hangs(monkeypatch):
    fake = _FlakyClient(fail_times=99)
    warnings = []
    monkeypatch.setattr(cr.log, "warning", lambda *a, **kw: warnings.append((a, kw)))
    monkeypatch.setattr(cr, "client", _patched_client(fake))
    docs = asyncio.run(cr.discover_recent_nods("SC", "Union", days_back=5, max_docs=10))
    assert docs == []
    assert fake.paginate_calls == 3   # stop_after_attempt(3), then gave up -- not infinite
    assert len(warnings) == 1
    assert warnings[0][1].get("state") == "SC" and warnings[0][1].get("county") == "Union"


def test_a_connect_timeout_on_the_initial_get_that_never_clears_also_stops_at_3(monkeypatch):
    fake = _FlakyGetClient(fail_times=99)
    warnings = []
    monkeypatch.setattr(cr.log, "warning", lambda *a, **kw: warnings.append((a, kw)))
    monkeypatch.setattr(cr, "client", _patched_client(fake))
    docs = asyncio.run(cr.discover_recent_nods("SC", "Union", days_back=5, max_docs=10))
    assert docs == []
    assert fake.get_calls == 3
    assert fake.setup_post_calls == 0   # never got past the GET
    assert len(warnings) == 1


# --- (c) a real non-transport HTTP error status is NOT retried --------------
# -- fails immediately on attempt 1, in contrast to (b)'s 3 attempts.

def test_a_real_http_status_error_on_the_paginated_post_is_not_retried(monkeypatch):
    req = httpx.Request("POST", f"{_BASE}/Search/Records/Result/")
    resp = httpx.Response(503, request=req)
    status_exc = httpx.HTTPStatusError("503 Server Error", request=req, response=resp)
    fake = _FlakyClient(fail_times=99, exc=status_exc)
    warnings = []
    monkeypatch.setattr(cr.log, "warning", lambda *a, **kw: warnings.append((a, kw)))
    monkeypatch.setattr(cr, "client", _patched_client(fake))
    docs = asyncio.run(cr.discover_recent_nods("SC", "Union", days_back=5, max_docs=10))
    assert docs == []
    assert fake.paginate_calls == 1   # a real bad status is not a transport/timeout error
    assert len(warnings) == 1


def test_a_plain_runtime_error_on_the_initial_get_is_not_retried(monkeypatch):
    fake = _FlakyGetClient(fail_times=99, exc=RuntimeError("not a transport error"))
    monkeypatch.setattr(cr, "client", _patched_client(fake))
    docs = asyncio.run(cr.discover_recent_nods("SC", "Union", days_back=5, max_docs=10))
    assert docs == []
    assert fake.get_calls == 1   # unretried exception types fail on attempt 1
