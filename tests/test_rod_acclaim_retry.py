"""rod.acclaim._search_chunk / discover_recent_nods: a transient transport error on
one of the raw AcclaimWeb calls gets retried, not treated as "the whole sweep failed."

Found 2026-11-07 (same proven bug shape already fixed tonight for the Column
legal-notice API scraper, spartan_weekly_legals.py, and arcgis_webmap.query_features()):
rod/acclaim.py's _search_chunk() makes two raw c.post() calls (the date-window search,
then GridResults) and discover_recent_nods() makes one raw c.get() (the session-cookie
primer) -- all three through the bare http_client.client() context manager, which
deliberately carries retries=0 ("callers already wrap their own AsyncRetrying").
None of the three had any retry cushioning of their own, and the ENTIRE multi-chunk
sweep in discover_recent_nods sits under one outer `except Exception: log + return
partial/empty out`, which silently swallows a transient blip instead of retrying it.
ACCLAIM_COUNTIES has exactly one county (Pickens, SC) today, so a single transient
blip anywhere in this chain used to zero this scraper's entire run output, reported
as a healthy empty result rather than a visible failure.
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.rod import acclaim

BASE = "https://www.example-rod.test/AcclaimWeb"
FROM = datetime(2026, 10, 1)
TO = datetime(2026, 10, 10)


class _FakeResp:
    def __init__(self, text="", status_code=200, json_data=None, content_type="application/json"):
        self.text = text
        self.status_code = status_code
        self._json = {} if json_data is None else json_data
        self.headers = {"content-type": content_type}

    def json(self):
        return self._json


class _FlakyPostClient:
    """Fake client for _search_chunk: .post() raises on the first `fail_times` calls
    whose URL contains `fail_on`, then serves a real terminal response. Tracks
    matching-call count separately from total calls so each retry site (the
    SearchTypeDocType search vs. the GridResults fetch) can be asserted on its own."""

    def __init__(self, fail_on: str, fail_times: int, exc=None,
                 search_text="ok", grid_rows=None, grid_status=200):
        self.fail_on = fail_on
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls_matching = 0
        self.search_text = search_text
        self.grid_rows = [] if grid_rows is None else grid_rows
        self.grid_status = grid_status

    async def post(self, url, data=None, headers=None):
        if self.fail_on in url:
            self.calls_matching += 1
            if self.calls_matching <= self.fail_times:
                raise self.exc
        if "GridResults" in url:
            return _FakeResp(status_code=self.grid_status, json_data={"data": self.grid_rows})
        return _FakeResp(text=self.search_text, status_code=200)


class _FakeDiscoverClient:
    """Fake client for discover_recent_nods: .get() (the session-cookie primer) is
    flaky per fail_times/exc; .post() always succeeds immediately with an empty
    grid page, so the sweep's per-chunk work is a no-op and the test stays focused
    on the .get() retry site."""

    def __init__(self, fail_times: int, exc=None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.get_calls = 0

    async def get(self, url):
        self.get_calls += 1
        if self.get_calls <= self.fail_times:
            raise self.exc
        return _FakeResp(status_code=200)

    async def post(self, url, data=None, headers=None):
        if "GridResults" in url:
            return _FakeResp(status_code=200, json_data={"data": []})
        return _FakeResp(text="ok", status_code=200)


def _patch_client(monkeypatch, fake) -> None:
    @contextlib.asynccontextmanager
    async def _fake_cm(*, timeout=45.0):
        yield fake

    monkeypatch.setattr(acclaim, "client", _fake_cm)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(acclaim, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# --- _search_chunk: the first POST (date-window search) ---------------------
def test_search_post_transient_connect_timeout_is_retried_and_then_succeeds():
    http = _FlakyPostClient(fail_on="SearchTypeDocType", fail_times=2,
                            grid_rows=[{"DocType": "D/DIST"}])
    rows = asyncio.run(acclaim._search_chunk(http, BASE, FROM, TO))
    assert http.calls_matching == 3   # 2 failures + 1 success
    assert rows == [{"DocType": "D/DIST"}]


def test_search_post_transient_error_that_never_clears_still_raises_not_hangs():
    http = _FlakyPostClient(fail_on="SearchTypeDocType", fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(acclaim._search_chunk(http, BASE, FROM, TO))
    assert http.calls_matching == 3   # stop_after_attempt(3), then gives up


def test_search_post_show_error_body_is_not_retried():
    """A real 'window too large' ShowError body is a genuine terminal outcome
    (caller is told to use a smaller window), not a transient blip -- must not
    trigger a retry."""
    http = _FlakyPostClient(fail_on="SearchTypeDocType", fail_times=0,
                            search_text="ShowError: date range exceeded limit")
    rows = asyncio.run(acclaim._search_chunk(http, BASE, FROM, TO))
    assert rows == []
    assert http.calls_matching == 1   # the call itself succeeded; nothing to retry


# --- _search_chunk: the second POST (GridResults) ----------------------------
def test_grid_post_transient_read_timeout_is_also_retried():
    http = _FlakyPostClient(fail_on="GridResults", fail_times=1,
                            exc=httpx.ReadTimeout("slow"),
                            grid_rows=[{"DocType": "LIEN"}])
    rows = asyncio.run(acclaim._search_chunk(http, BASE, FROM, TO))
    assert http.calls_matching == 2
    assert rows == [{"DocType": "LIEN"}]


def test_grid_post_transient_error_that_never_clears_still_raises_not_hangs():
    http = _FlakyPostClient(fail_on="GridResults", fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(acclaim._search_chunk(http, BASE, FROM, TO))
    assert http.calls_matching == 3


def test_grid_post_bad_status_is_not_retried():
    """A real non-200 from GridResults is a genuine terminal outcome (the function
    returns [] by design), not a transport failure -- must not trigger a retry."""
    http = _FlakyPostClient(fail_on="GridResults", fail_times=0, grid_status=503)
    rows = asyncio.run(acclaim._search_chunk(http, BASE, FROM, TO))
    assert rows == []
    assert http.calls_matching == 1


def test_grid_post_non_json_content_type_is_not_retried():
    """A real non-JSON response (e.g. an HTML error page with a 200) is a terminal
    outcome too -- must not trigger a retry."""
    http = _FlakyPostClient(fail_on="GridResults", fail_times=0, grid_status=200)
    # Force a non-json content-type on the grid response.
    orig_post = http.post

    async def _post(url, data=None, headers=None):
        resp = await orig_post(url, data=data, headers=headers)
        if "GridResults" in url:
            resp.headers = {"content-type": "text/html"}
        return resp

    http.post = _post
    rows = asyncio.run(acclaim._search_chunk(http, BASE, FROM, TO))
    assert rows == []
    assert http.calls_matching == 1


# --- discover_recent_nods: the initial c.get() session-cookie primer --------
def test_discover_session_cookie_transient_timeout_is_retried_and_sweep_succeeds(monkeypatch):
    fake = _FakeDiscoverClient(fail_times=2)
    _patch_client(monkeypatch, fake)
    docs = asyncio.run(acclaim.discover_recent_nods("SC", "Pickens", days_back=5))
    assert fake.get_calls == 3   # 2 failures + 1 success -- the sweep is NOT zeroed
    assert docs == []            # empty grid pages -> no distress docs, but it ran clean


def test_discover_session_cookie_persistent_timeout_does_not_hang_returns_partial(monkeypatch):
    fake = _FakeDiscoverClient(fail_times=99)
    _patch_client(monkeypatch, fake)
    docs = asyncio.run(acclaim.discover_recent_nods("SC", "Pickens", days_back=5))
    # stop_after_attempt(3) on the priming call exhausts, reraise=True propagates it,
    # and discover_recent_nods's own outer except catches it and returns promptly --
    # not an infinite hang, and not a crash.
    assert fake.get_calls == 3
    assert docs == []
