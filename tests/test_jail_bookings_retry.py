"""national.jail_bookings: a transient transport/timeout error on a vendor fetcher's
network call gets retried, not treated as "that county's whole roster is empty."

FOUND 2026-11-07 (gap-sweep, proven-bug-shape audit): every vendor fetcher in
jail_bookings.py made its primary network call(s) inside a bare try/except Exception
with zero retry cushioning -- the same root cause already fixed tonight for the Column
legal-notice API scrapers, spartan_weekly_legals.py, and arcgis_webmap.query_features().
A single transient connection reset or timeout permanently zeroed that ONE county's
entire in-custody roster for the run, and because this scraper's slug
("national.jail_bookings") is in main.DATELESS_OK_SOURCES, there is no fallback date
window to self-heal on -- a zeroed county just silently reports empty until someone
notices by hand.

Unlike the httpx-based scrapers already fixed, this file's HTTP client is curl_cffi
(`AsyncSession(impersonate="chrome", ...)`), which raises its OWN exception hierarchy
(curl_cffi.requests.exceptions.*) -- NOT httpx's, and NOT the builtin TimeoutError/
ConnectionError. The shared `_vendor_retrying()` helper added by this fix retries only
curl_cffi's own ConnectionError/Timeout (confirmed below this correctly covers
ConnectTimeout, since it subclasses both), never a real HTTP-error-shaped exception.

This module tests the shared `_vendor_retrying()` controller directly (the single
mechanism every wrapped call site shares) plus two independently-wrapped call sites --
`_fetch_zuercher` (the brief's own representative, highest-leverage example) and
`_fetch_randolph_webforms` (a second, differently-shaped fetcher) -- to prove the fix
was actually applied across the file's many call sites, not just to one function.
"""
from __future__ import annotations

import asyncio

import pytest
from curl_cffi.requests import exceptions as cce
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import jail_bookings as jb

ZUERCHER_SUBDOMAIN = "cherokee-so-sc"
RANDOLPH_TARGET = "https://www.co.randolph.nc.us/sheriff/confinedinmatesbydate.aspx"


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #

class _FakeJsonResp:
    """Stand-in for a curl_cffi Response whose body is read via .json()."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeTextResp:
    """Stand-in for a curl_cffi Response whose body is read via the .text attribute."""

    def __init__(self, text=""):
        self.text = text


class _FlakyPostSession:
    """Stand-in for curl_cffi's AsyncSession. Raises on the first `fail_times` POSTs,
    then serves a real (empty, terminal) roster response -- same shape as
    _FlakyHttp in test_arcgis_webmap_query_features_retry.py, adapted to curl_cffi's
    AsyncSession interface (async context manager + .post()) instead of an injected
    httpx-style client."""

    def __init__(self, fail_times: int, exc):
        self.fail_times = fail_times
        self.exc = exc
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeJsonResp({"records": []})


class _FlakyGetSession:
    """Same idea as _FlakyPostSession, for a GET-only fetcher."""

    def __init__(self, fail_times: int, exc):
        self.fail_times = fail_times
        self.exc = exc
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeTextResp("")


def _patch_session(monkeypatch, fake):
    # curl_cffi.requests.AsyncSession is imported locally inside each fetcher
    # (this file's own established lazy-import convention), so the fake must be
    # installed on the real curl_cffi.requests module -- same technique already
    # used by test_jail_bookings_buncombe.py / test_jail_bookings_new_counties.py
    # for this exact file's fetchers.
    import curl_cffi.requests as ccr
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: fake)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(jb, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# --------------------------------------------------------------------------- #
# (a) a transient transport/timeout error is retried and then succeeds       #
# --------------------------------------------------------------------------- #

def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyPostSession(fail_times=2, exc=cce.ConnectTimeout("boom"))
    _patch_session(monkeypatch, fake)

    recs = asyncio.run(jb._fetch_zuercher(ZUERCHER_SUBDOMAIN))

    assert fake.calls == 3
    assert recs == []  # the terminal response is a real, empty, healthy roster


def test_a_read_timeout_is_also_retried(monkeypatch):
    fake = _FlakyPostSession(fail_times=1, exc=cce.ReadTimeout("slow"))
    _patch_session(monkeypatch, fake)

    recs = asyncio.run(jb._fetch_zuercher(ZUERCHER_SUBDOMAIN))

    assert fake.calls == 2
    assert recs == []


def test_the_fix_was_also_applied_to_other_fetchers_not_just_zuercher(monkeypatch):
    """_fetch_randolph_webforms is a second, independently-wrapped call site -- proves
    the sweep covered more than the one representative fetcher (the brief's own note:
    "a fix to _fetch_zuercher alone is NOT sufficient for this file")."""
    fake = _FlakyGetSession(fail_times=2, exc=cce.ConnectTimeout("boom"))
    _patch_session(monkeypatch, fake)

    recs = asyncio.run(jb._fetch_randolph_webforms(RANDOLPH_TARGET))

    assert fake.calls == 3
    assert recs == []


# --------------------------------------------------------------------------- #
# (b) a transient error that never clears still raises, not hangs            #
# --------------------------------------------------------------------------- #

def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    """Direct test of the shared _vendor_retrying() controller -- every one of the
    file's ~19 wrapped call sites shares this exact budget/predicate, so proving it
    here once is stronger than proving it through any single fetcher's own outer
    try/except (which, by design, still swallows the final raise -- see the
    integration-level version of this same scenario below)."""
    calls = {"n": 0}

    async def _always_fails():
        calls["n"] += 1
        raise cce.ConnectTimeout("boom")

    async def _run():
        async for attempt in jb._vendor_retrying():
            with attempt:
                await _always_fails()

    with pytest.raises(cce.ConnectTimeout):
        asyncio.run(_run())
    assert calls["n"] == 3  # stop_after_attempt(3), then gives up -- not an infinite hang


def test_zuercher_still_returns_empty_not_hung_when_retries_exhaust(monkeypatch):
    """Integration-level counterpart: _fetch_zuercher's own pre-existing outer
    try/except (unchanged by this fix) still catches the exhausted-retry exception and
    returns [] gracefully, exactly as it did before this fix for any other failure --
    the retry wrap only adds up to 2 extra attempts, it never changes what happens once
    attempts are exhausted."""
    fake = _FlakyPostSession(fail_times=99, exc=cce.ConnectTimeout("boom"))
    _patch_session(monkeypatch, fake)

    recs = asyncio.run(jb._fetch_zuercher(ZUERCHER_SUBDOMAIN))

    assert fake.calls == 3  # capped by stop_after_attempt(3), not retried forever
    assert recs == []


# --------------------------------------------------------------------------- #
# (c) a real non-transport error is NOT retried (fails on attempt 1)         #
# --------------------------------------------------------------------------- #

def test_a_real_http_error_is_not_retried():
    """Direct test of the shared controller: a genuine bad-status-shaped curl_cffi
    exception (HTTPError, what raise_for_status() raises -- not a subclass of
    ConnectionError or Timeout) must fail immediately, never consume a retry slot."""
    calls = {"n": 0}

    async def _bad_status():
        calls["n"] += 1
        raise cce.HTTPError("503 Server Error")

    async def _run():
        async for attempt in jb._vendor_retrying():
            with attempt:
                await _bad_status()

    with pytest.raises(cce.HTTPError):
        asyncio.run(_run())
    assert calls["n"] == 1  # a real bad-status error is not a transport/timeout error


def test_zuercher_does_not_retry_a_real_http_error(monkeypatch):
    """Integration-level counterpart on the representative fetcher: the fake session
    raises a real, non-transport curl_cffi error on the very first call; the retry
    wrap must not mask it with extra attempts, and _fetch_zuercher's own pre-existing
    outer except still turns it into a graceful empty result, same as always."""
    fake = _FlakyPostSession(fail_times=1, exc=cce.HTTPError("503 Server Error"))
    _patch_session(monkeypatch, fake)

    recs = asyncio.run(jb._fetch_zuercher(ZUERCHER_SUBDOMAIN))

    assert fake.calls == 1  # failed immediately on attempt 1, never retried
    assert recs == []       # _fetch_zuercher's own outer except, unchanged, catches it


def test_a_json_decode_error_on_a_bad_body_is_not_retried(monkeypatch):
    """A second, more realistic non-transport failure mode for this specific
    function: the vendor returns a 200 whose body is not valid JSON (e.g. an error
    page) -- .json() raises curl_cffi's own InvalidJSONError, which this fetcher's
    outer except already handled before this fix and must go on handling unretried."""

    class _BadBodySession:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, timeout=None):
            self.calls += 1

            class _BadResp:
                def json(self):
                    raise cce.JSONDecodeError("not json", "", 0)
            return _BadResp()

    fake = _BadBodySession()
    _patch_session(monkeypatch, fake)

    recs = asyncio.run(jb._fetch_zuercher(ZUERCHER_SUBDOMAIN))

    assert fake.calls == 1
    assert recs == []
