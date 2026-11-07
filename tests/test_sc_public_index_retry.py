"""scrapers.national.sc_public_index: a transient curl_cffi transport/timeout error on a
Charleston network call gets retried, not treated as "the whole scrape failed."

Confirmed 2026-11-07 (bug-shape sweep, same root cause already fixed tonight for a Column
legal-notice API scraper, spartan_weekly_legals.py, the shared arcgis_webmap.query_features()
function, and sc_public_index_lis_pendens.py -- a differently-named sibling module, NOT this
file): three curl_cffi network calls in this file had zero retry cushioning of their own --

  1. _curl_search_county()'s disclaimer GET (step 1) and accept POST (step 2): true
     single-points-of-failure. Either one raising propagates uncaught to this function's own
     catch-all `except Exception`, which zeros Charleston's ENTIRE result for the run on one
     transient network blip.
  2. The nested `post()` closure inside _date_window_search() (called up to
     WINDOW_MAX_REQUESTS times a run, from the court/case postback branches, the main
     filed-date sweep, and _letters_with_date()): the single most exposed site, since any one
     of up to 40 calls failing propagated the same way, discarding the whole results list
     accumulated so far for Charleston this run -- not just the one window in flight.

Because this scraper is registered in main.DATELESS_OK_SOURCES semantics, a window/county
zeroed by one transient blip is never backfilled by a later run.

Unlike the arcgis_webmap/Column fixes (httpx-based), this file's real HTTP calls all go
through curl_cffi.requests, so the retry condition targets curl_cffi's own connection/timeout
exception classes (curl_cffi.requests.exceptions.ConnectionError / Timeout) plus the builtin
TimeoutError, instead of httpx.TransportError / httpx.TimeoutException. A real non-200 status
(curl_cffi does not raise on a bad status by itself -- the caller checks status_code) is still
handled exactly as before, unretried.

NOT covered here (deliberately out of scope for this fix): the per-prefix search POST inside
_curl_search_county()'s `for prefix in SEARCH_PREFIXES:` loop (around the module's SEARCH_
PREFIXES sweep) is already locally wrapped in `try: ... except Exception: continue`, so a
transient failure there only drops that one prefix's results -- a bounded, already-scoped
blast radius, not the single-point-of-failure shape fixed here.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest
from curl_cffi import requests as cf_requests
from curl_cffi.requests import exceptions as curl_exceptions
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import sc_public_index as mod


# --------------------------------------------------------------------------- #
# Fakes. Plain sync callables (never `async def`) -- the real code always runs
# session.get/session.post through asyncio.to_thread, exactly like curl_cffi's actual
# (synchronous) Session.get/Session.post.
# --------------------------------------------------------------------------- #

class _FakeResp:
    def __init__(self, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FlakyCall:
    """Raises on the first N-1 calls, then returns a real (terminal) response."""

    def __init__(self, fail_times: int, exc: Exception | None = None,
                 ok_text: str = "<html>ok</html>", ok_status: int = 200):
        self.fail_times = fail_times
        self.exc = exc or curl_exceptions.ConnectionError("connection reset")
        self.ok_text = ok_text
        self.ok_status = ok_status
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp(status_code=self.ok_status, text=self.ok_text)


class _AlwaysOk:
    """Never raises; returns a fixed response every call. Counts calls."""

    def __init__(self, status: int = 200, text: str = ""):
        self.status = status
        self.text = text
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return _FakeResp(status_code=self.status, text=self.text)


class _FakeSession:
    """Mimics curl_cffi.requests.Session's .get/.post -- plain attributes, not bound
    methods, matching how _curl_search_county/_date_window_search call them."""

    def __init__(self, get_impl=None, post_impl=None):
        self.get = get_impl
        self.post = post_impl


@pytest.fixture(autouse=True)
def _fast_and_hermetic(monkeypatch):
    """Keep every test's backoff/pacing sleeps near-instant, pin the date-window search's
    request budget/lookback to small deterministic values, and never touch the real on-disk
    Charleston state file (_date_window_search persists its incremental cursor there --
    irrelevant to, and a source of flakiness for, these retry-wrapper tests)."""
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))
    monkeypatch.setattr(mod, "REQUEST_DELAY", 0)
    monkeypatch.setattr(mod, "WINDOW_DELAY", 0)
    monkeypatch.setattr(mod, "WINDOW_MAX_REQUESTS", 1)
    monkeypatch.setattr(mod, "FILED_LOOKBACK_DAYS", 10)
    monkeypatch.setattr(mod, "_load_state", lambda: {})
    monkeypatch.setattr(mod, "_save_state", lambda state: None)


# --------------------------------------------------------------------------- #
# Group A: the nested post() closure inside _date_window_search() -- the single most
# exposed call site (up to WINDOW_MAX_REQUESTS times a run).
#
# Driven through the court-postback branch, the first thing _date_window_search() does
# once it has a date-filter form: it is the smallest surface that reaches post() exactly
# once and (via WINDOW_MAX_REQUESTS=1, pinned above) lets every later would-be call in the
# same run short-circuit for free, without touching the rest of the function's business
# logic (case-type postback, subtype plan, the window sweep) -- none of which this fix
# touches.
# --------------------------------------------------------------------------- #

_FORM = {
    "court": "ctl00$Court", "court_value": "1", "court_postback": True,
    "filed": "filedOptionValue",
    "date_filter": "ctl00$DateFilter", "from": "ctl00$DateFrom", "to": "ctl00$DateTo",
}
_PAGE_HTML = "<html><body>no relevant selects here</body></html>"
_TODAY = date(2026, 1, 15)


def _run_date_window_search(session):
    return asyncio.run(mod._date_window_search(
        session, "https://jcmsweb.charlestoncounty.org/PublicIndex/PISearch.aspx",
        _PAGE_HTML, dict(_FORM), [], {}, today=_TODAY))


def test_a_transient_connection_error_is_retried_and_then_succeeds():
    post_impl = _FlakyCall(fail_times=2, exc=curl_exceptions.ConnectionError("connection reset"))
    result = _run_date_window_search(_FakeSession(post_impl=post_impl))
    assert post_impl.calls == 3
    assert result.get("fallback") is None
    assert result["requests"] == 1


def test_a_transient_curl_timeout_is_also_retried():
    post_impl = _FlakyCall(fail_times=1, exc=curl_exceptions.Timeout("operation timed out"))
    result = _run_date_window_search(_FakeSession(post_impl=post_impl))
    assert post_impl.calls == 2
    assert result.get("fallback") is None
    assert result["requests"] == 1


def test_a_builtin_timeout_error_is_also_retried():
    """The plain builtin TimeoutError hedge (mirrors the httpx-based fixes' third type)."""
    post_impl = _FlakyCall(fail_times=1, exc=TimeoutError("asyncio timeout"))
    result = _run_date_window_search(_FakeSession(post_impl=post_impl))
    assert post_impl.calls == 2
    assert result.get("fallback") is None


def test_a_transient_error_that_never_clears_raises_after_retry_budget_not_hangs():
    post_impl = _FlakyCall(fail_times=99, exc=curl_exceptions.ConnectionError("connection reset"))
    with pytest.raises(curl_exceptions.ConnectionError):
        _run_date_window_search(_FakeSession(post_impl=post_impl))
    assert post_impl.calls == 3  # stop_after_attempt(3), then gives up -- no infinite retry


def test_a_bad_http_status_is_not_retried():
    post_impl = _AlwaysOk(status=503)
    result = _run_date_window_search(_FakeSession(post_impl=post_impl))
    assert post_impl.calls == 1  # a real bad status is not a transport/timeout error
    assert result.get("fallback") == "court_postback_failed"


# --------------------------------------------------------------------------- #
# Group B: _curl_search_county()'s disclaimer GET (step 1) and accept POST (step 2) --
# the two SPOF siblings. curl_cffi.requests.Session is monkeypatched so the function's
# own local `from curl_cffi import requests as cf; session = cf.Session()` returns our
# fake. When one step's response carries no hidden <input> fields, _get_hidden_fields()
# returns {} and the function returns [] right after -- the natural, un-forced place both
# steps' flows terminate, so each test only needs to make ONE side flaky/failing and
# leave the other immediately successful.
# --------------------------------------------------------------------------- #

def _run_curl_search_county(monkeypatch, get_impl, post_impl):
    monkeypatch.setattr(cf_requests, "Session", lambda: _FakeSession(get_impl, post_impl))
    return asyncio.run(mod._curl_search_county("charleston"))


def test_curl_search_county_get_disclaimer_retries_transient_error_then_succeeds(monkeypatch):
    get_impl = _FlakyCall(fail_times=2, exc=curl_exceptions.ConnectionError("connection reset"))
    result = _run_curl_search_county(monkeypatch, get_impl, _AlwaysOk())
    assert get_impl.calls == 3
    assert result == []


def test_curl_search_county_get_disclaimer_error_never_clears_still_returns_empty_not_hangs(monkeypatch):
    get_impl = _FlakyCall(fail_times=99, exc=curl_exceptions.ConnectionError("connection reset"))
    result = _run_curl_search_county(monkeypatch, get_impl, _AlwaysOk())
    # stop_after_attempt(3), then _curl_search_county's own pre-existing outer
    # `except Exception` catches it and returns [] -- same terminal, un-regressed
    # behavior as before this fix for a truly-dead connection; the improvement is that
    # a merely-transient blip (the common case) never reaches that catch-all at all.
    assert get_impl.calls == 3
    assert result == []


def test_curl_search_county_post_accept_retries_transient_error_then_succeeds(monkeypatch):
    post_impl = _FlakyCall(fail_times=2, exc=curl_exceptions.Timeout("operation timed out"))
    result = _run_curl_search_county(monkeypatch, _AlwaysOk(), post_impl)
    assert post_impl.calls == 3
    assert result == []


def test_curl_search_county_post_accept_error_never_clears_still_returns_empty_not_hangs(monkeypatch):
    post_impl = _FlakyCall(fail_times=99, exc=curl_exceptions.Timeout("operation timed out"))
    result = _run_curl_search_county(monkeypatch, _AlwaysOk(), post_impl)
    assert post_impl.calls == 3  # stop_after_attempt(3), then gives up -- no infinite retry
    assert result == []


def test_curl_search_county_disclaimer_bad_status_not_retried(monkeypatch):
    get_impl = _AlwaysOk(status=503)
    result = _run_curl_search_county(monkeypatch, get_impl, _AlwaysOk())
    assert get_impl.calls == 1  # a real bad status is not a transport/timeout error
    assert result == []
