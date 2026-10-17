"""gannett_obituaries: a transient transport error on the Tukios list-page GET or the
per-decedent detail GET gets retried, not treated as "the whole paper/decedent failed."

Found 2026-10-17 (gap-sweep): both GannettObituaries.fetch()'s list-page fetch
(``c.get(f"https://www.{host}/obituaries/")``) and ``_fetch_detail_status()``'s
per-decedent detail fetch (``c.get(url)``) go through the bare, retries=0 ``client()``
(http_client.py deliberately ships ``AsyncHTTPTransport(retries=0)`` and expects every
caller to wrap its own ``AsyncRetrying``) with zero retry cushioning -- the same root
cause already fixed tonight for the Column legal-notice API scraper,
spartan_weekly_legals.py, and arcgis_webmap.query_features(). A single transient blip on
the list-page GET used to permanently zero that WHOLE paper's rows for the run (not just
one item), and because this source is registered in main.DATELESS_OK_SOURCES (no
fallback date window) that loss could never self-heal on a later run. The TownNews RSS
path (``_fetch_townnews_host`` -> ``get_text(..., impersonate=True)``) is NOT covered
here because it already wraps its own retries inside ``get_text`` itself.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from tenacity import wait_exponential_jitter

import foreclosure_scraper.scrapers.public_notices.gannett_obituaries as M

LIST_HTML = '<a href="/obituaries/jerry-deal">Jerry Deal</a>'
DETAIL_HTML = (
    '<html><head><meta name="description" content="Jerry Deal, 92, of '
    'Asheville, North Carolina, passed away on September 30, 2026."></head></html>'
)


class _FakeResp:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code


class _FlakyClient:
    """Raises on the first N-1 ``.get()`` calls, then serves a real response."""

    def __init__(self, fail_times: int, exc=None, ok_resp: _FakeResp | None = None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.ok_resp = ok_resp or _FakeResp(LIST_HTML, 200)
        self.calls = 0

    async def get(self, url, **kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.ok_resp


def _fake_client_cm(stub):
    @asynccontextmanager
    async def _cm(*a, **kw):
        yield stub
    return _cm


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(M, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# ---------------------------------------------------------------------------
# _fetch_detail_status: per-decedent detail GET
# ---------------------------------------------------------------------------

def test_detail_fetch_a_transient_connect_timeout_is_retried_and_then_succeeds():
    c = _FlakyClient(fail_times=2, ok_resp=_FakeResp(DETAIL_HTML, 200))
    status, detail = asyncio.run(M._fetch_detail_status(c, "http://x/obituaries/jerry-deal"))
    assert c.calls == 3
    assert status == 200
    assert detail["age"] == 92


def test_detail_fetch_a_connect_timeout_that_never_clears_still_returns_not_hangs():
    """Never raises out of _fetch_detail_status -- the list-only lead this scraper
    already had must survive -- but it must give up after the retry budget, not hang."""
    c = _FlakyClient(fail_times=99)
    status, detail = asyncio.run(M._fetch_detail_status(c, "http://x/obituaries/jerry-deal"))
    assert c.calls == 3  # stop_after_attempt(3), then gives up
    assert status is None
    assert detail == {}


def test_detail_fetch_a_read_timeout_is_also_retried():
    c = _FlakyClient(fail_times=1, exc=httpx.ReadTimeout("slow"),
                     ok_resp=_FakeResp(DETAIL_HTML, 200))
    status, detail = asyncio.run(M._fetch_detail_status(c, "http://x/obituaries/jerry-deal"))
    assert c.calls == 2
    assert status == 200
    assert detail["age"] == 92


def test_detail_fetch_a_real_http_error_status_is_not_retried():
    class _BadStatusClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, **kw):
            self.calls += 1
            return _FakeResp("", 404)

    c = _BadStatusClient()
    status, detail = asyncio.run(M._fetch_detail_status(c, "http://x/obituaries/missing"))
    assert c.calls == 1   # a real bad status is not a transport/timeout error
    assert status == 404
    assert detail == {}


def test_detail_fetch_a_non_transport_exception_is_not_retried():
    """A plain OSError (e.g. connection reset) is caught by the outer try/except, same
    as before this fix, and must not be retried -- only transport/timeout errors are."""
    class _BrokenClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, **kw):
            self.calls += 1
            raise OSError("connection reset")

    c = _BrokenClient()
    status, detail = asyncio.run(M._fetch_detail_status(c, "http://x/obituaries/broken"))
    assert c.calls == 1
    assert status is None
    assert detail == {}


# ---------------------------------------------------------------------------
# GannettObituaries.fetch(): Tukios list-page GET
# ---------------------------------------------------------------------------

def test_list_page_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    c = _FlakyClient(fail_times=2, ok_resp=_FakeResp(LIST_HTML, 200))
    monkeypatch.setattr(M, "client", _fake_client_cm(c))
    monkeypatch.setattr(M, "PAPERS", {"citizen-times.com": ("Buncombe", "NC")})
    monkeypatch.setattr(M, "_GAP_S", 0.0, raising=False)
    monkeypatch.setenv("FORECLOSURE_OBIT_DETAIL", "0")

    result = list(asyncio.run(M.GannettObituaries().fetch()))
    assert c.calls == 3   # 2 failures, then the real list page
    assert len(result) == 1
    assert result[0].defendant == "Jerry Deal"


def test_list_page_a_connect_timeout_that_never_clears_still_yields_no_rows_not_hangs(monkeypatch):
    """fetch()'s own try/except around the list-page GET must still catch the
    exhausted-retries error and move on (rows so far ship), not hang or crash the run."""
    c = _FlakyClient(fail_times=99)
    monkeypatch.setattr(M, "client", _fake_client_cm(c))
    monkeypatch.setattr(M, "PAPERS", {"citizen-times.com": ("Buncombe", "NC")})
    monkeypatch.setattr(M, "_GAP_S", 0.0, raising=False)
    monkeypatch.setenv("FORECLOSURE_OBIT_DETAIL", "0")

    result = list(asyncio.run(M.GannettObituaries().fetch()))
    assert c.calls == 3   # stop_after_attempt(3), then gives up
    assert result == []


def test_list_page_a_real_http_error_status_is_not_retried(monkeypatch):
    class _BadStatusClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, **kw):
            self.calls += 1
            return _FakeResp("", 503)

    c = _BadStatusClient()
    monkeypatch.setattr(M, "client", _fake_client_cm(c))
    monkeypatch.setattr(M, "PAPERS", {"citizen-times.com": ("Buncombe", "NC")})
    monkeypatch.setattr(M, "_GAP_S", 0.0, raising=False)
    monkeypatch.setenv("FORECLOSURE_OBIT_DETAIL", "0")

    result = list(asyncio.run(M.GannettObituaries().fetch()))
    assert c.calls == 1   # a real bad status is not a transport/timeout error
    assert result == []


def test_list_page_a_429_is_not_retried_and_stops_the_pass(monkeypatch):
    """429 is a real status, not a transport error -- it must not be retried, and the
    existing shared-edge-throttle behavior (stop the Gannett pass) is unchanged."""
    class _ThrottledClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, **kw):
            self.calls += 1
            return _FakeResp("Too Many Requests", 429)

    c = _ThrottledClient()
    monkeypatch.setattr(M, "client", _fake_client_cm(c))
    monkeypatch.setattr(M, "PAPERS", {"citizen-times.com": ("Buncombe", "NC"),
                                      "blueridgenow.com": ("Henderson", "NC")})
    monkeypatch.setattr(M, "_GAP_S", 0.0, raising=False)
    monkeypatch.setenv("FORECLOSURE_OBIT_DETAIL", "0")

    result = list(asyncio.run(M.GannettObituaries().fetch()))
    assert c.calls == 1   # the 429 stops the pass -- the 2nd paper is never asked
    assert result == []
