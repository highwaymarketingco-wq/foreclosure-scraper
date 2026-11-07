"""bid4assets.py: a transient curl_cffi transport/timeout error on any of its
three network call sites gets retried, not treated as "the whole scrape
failed."

Found 2026-11-07 (gap-sweep): this file rolls its own
curl_cffi.requests.AsyncSession directly (_get_session_and_token) instead of
going through the project's shared http_client.client() helper, which has
tenacity AsyncRetrying built in -- so none of its three real network calls
got that helper's protection; each was independently unprotected.

Severity ranking (why all three get covered here, not just one):
  - _get_session_and_token's token-page GET is the single most severe call
    site in the file: Bid4Assets.fetch() returns [] immediately once `token`
    comes back falsy, before the per-state (NC, SC) loop ever starts -- one
    unretried transient blip there used to zero BOTH states' output for the
    whole run.
  - _fetch_state's search-results POST (the real search/listings call) is a
    SPOF scoped to one state: a blip on page 1 zeros that state's results.
  - _fetch_description_fields's per-auction GET is lower severity: it is
    explicitly "never raise" best-effort enrichment (its own docstring) --a
    failure only leaves two optional fields unset on one row, the Listing
    itself is unaffected. Still worth the same cushioning for robustness.

Nuance: this file's sessions are curl_cffi.requests.AsyncSession, not httpx --
curl_cffi raises its OWN exception hierarchy under
curl_cffi.requests.exceptions (ConnectionError, ConnectTimeout, ReadTimeout,
Timeout, DNSError, ...), confirmed in this project's venv (curl_cffi 0.15.0),
so these tests use REAL curl_cffi exception instances, not httpx ones -- and
all three call sites in this file already catch-and-gracefully-degrade by
design (return (s, None) / break the page loop / return {}), unlike
arcgis_webmap.query_features's bare raise, so "still raises after the retry
budget is exhausted" is proven two ways below: directly, by driving the same
retry primitive this file's call sites use against an isolated raising stub
(test_transient_exc_tuple_retries_then_raises_when_budget_exhausted); and
indirectly, by bounding each call site's own fake-session call count at 3
(stop_after_attempt(3) honored -- not an infinite retry/hang) while its
pre-existing graceful-degradation outcome is preserved unchanged."""
from __future__ import annotations

import asyncio

import pytest
from curl_cffi.requests.exceptions import ConnectTimeout, HTTPError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from foreclosure_scraper.scrapers.national import bid4assets as b4a


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(b4a, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


class _FakeResp:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data

    def json(self):
        return self._json


class _FlakySession:
    """Simulates curl_cffi.requests.AsyncSession: raises on the first
    `fail_times` calls to get()/post(), then serves a real (terminal)
    response. Mirrors `_FlakyHttp` in
    test_arcgis_webmap_query_features_retry.py."""

    def __init__(self, fail_times: int, exc=None, resp: _FakeResp | None = None):
        self.fail_times = fail_times
        self.exc = exc or ConnectTimeout("boom")
        self.resp = resp if resp is not None else _FakeResp(json_data={"data": [], "total": 0})
        self.calls = 0

    async def get(self, url, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.resp

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.resp


# --- the shared retry primitive itself, in isolation -----------------------
# (every call site below also has its own pre-existing catch-and-degrade
# contract, so this proves (b)/(c) directly against the real predicate this
# file's three call sites all share, independent of any one site's wrapper.)

def test_transient_exc_tuple_retries_then_raises_when_budget_exhausted():
    """(b): the predicate this file's three call sites all use really does
    raise once stop_after_attempt(3) is exhausted against a persistently
    transient curl_cffi error -- not an infinite retry loop/hang."""
    calls = {"n": 0}

    async def _drive():
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.001, max=0.002),
            retry=retry_if_exception_type(b4a._TRANSIENT_EXC),
            reraise=True,
        ):
            with attempt:
                calls["n"] += 1
                raise ConnectTimeout("boom")

    with pytest.raises(ConnectTimeout):
        asyncio.run(_drive())
    assert calls["n"] == 3


def test_transient_exc_tuple_does_not_match_http_error():
    """(c), predicate-level: curl_cffi's HTTPError must never be treated as
    transient -- this file never calls .raise_for_status() (status is
    checked manually), but the predicate itself must stay scoped to
    transport/timeout only, not any error curl_cffi can raise."""
    assert not issubclass(HTTPError, b4a._TRANSIENT_EXC)


# --- _fetch_state: the per-state search/listings POST (a SPOF per state) ---

def test_fetch_state_retries_a_transient_timeout_and_then_succeeds():
    s = _FlakySession(fail_times=2)
    out = asyncio.run(b4a._fetch_state(s, "tok", "NC", "national.bid4assets"))
    assert s.calls == 3
    assert out == []


def test_fetch_state_transient_timeout_that_never_clears_breaks_not_hangs():
    """A transient error that never clears must still bottom out quickly via
    _fetch_state's own pre-existing except-and-break (unchanged by this fix),
    not hang or retry forever."""
    s = _FlakySession(fail_times=99)
    out = asyncio.run(b4a._fetch_state(s, "tok", "NC", "national.bid4assets"))
    assert s.calls == 3   # stop_after_attempt(3), then the outer except catches it
    assert out == []


def test_fetch_state_real_http_error_status_is_not_retried():
    """A real non-transport HTTP error status must fail immediately on
    attempt 1 -- the response comes back without raising, so the retry
    predicate (which only fires on an exception) is never even consulted."""
    class _BadStatusSession:
        def __init__(self):
            self.calls = 0

        async def post(self, url, json=None, headers=None, timeout=None):
            self.calls += 1
            return _FakeResp(status_code=503)

    s = _BadStatusSession()
    out = asyncio.run(b4a._fetch_state(s, "tok", "NC", "national.bid4assets"))
    assert s.calls == 1   # a real bad status is not a transport/timeout error
    assert out == []


# --- _fetch_description_fields: per-item enrichment GET (lower severity) ---

_DESC_HTML = (
    "<html><body>Deed or Lien: Deed Sale Type: Live/In Person "
    "Number of Deeds: 3</body></html>"
)


def test_description_fields_retries_a_transient_timeout_and_then_succeeds():
    s = _FlakySession(fail_times=2, resp=_FakeResp(status_code=200, text=_DESC_HTML))
    out = asyncio.run(b4a._fetch_description_fields(s, 1314088))
    assert s.calls == 3
    assert out == {"deed_or_lien": "Deed", "sale_type": "Live/In Person"}


def test_description_fields_transient_timeout_that_never_clears_still_swallowed():
    """This function's whole contract is "never raise" (its own docstring):
    even after the retry budget is exhausted it must still return {} rather
    than propagate, and must not hang."""
    s = _FlakySession(fail_times=99)
    out = asyncio.run(b4a._fetch_description_fields(s, 1))
    assert s.calls == 3
    assert out == {}


def test_description_fields_real_http_error_status_is_not_retried():
    class _BadStatusSession:
        def __init__(self):
            self.calls = 0

        async def get(self, url, timeout=None):
            self.calls += 1
            return _FakeResp(status_code=404, text="not found")

    s = _BadStatusSession()
    out = asyncio.run(b4a._fetch_description_fields(s, 1))
    assert s.calls == 1
    assert out == {}


# --- _get_session_and_token: the file's single most severe call site -------
# (fetch() returns [] immediately on a falsy token, before either state's
# loop starts -- one unretried blip here used to zero the WHOLE run.)

class _FlakyTokenSession:
    """Stands in for the real curl_cffi.requests.AsyncSession instance that
    `_get_session_and_token` constructs via AsyncSession(impersonate="chrome")."""

    def __init__(self, fail_times: int, exc=None, resp: _FakeResp | None = None):
        self.fail_times = fail_times
        self.exc = exc or ConnectTimeout("boom")
        self.resp = resp if resp is not None else _FakeResp(
            text='<input name="__RequestVerificationToken" value="tok123">'
        )
        self.calls = 0

    async def get(self, url, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.resp

    async def close(self):
        pass


def _patch_async_session(monkeypatch, fake_session):
    import curl_cffi.requests as cc_requests
    monkeypatch.setattr(cc_requests, "AsyncSession", lambda **kw: fake_session)


def test_get_session_and_token_retries_a_transient_timeout_and_then_succeeds(monkeypatch):
    fake = _FlakyTokenSession(fail_times=2)
    _patch_async_session(monkeypatch, fake)
    s, token = asyncio.run(b4a._get_session_and_token())
    assert fake.calls == 3
    assert token == "tok123"
    assert s is fake


def test_get_session_and_token_transient_timeout_that_never_clears_degrades_not_hangs(monkeypatch):
    """The single most severe call site in the file: zeroes BOTH states'
    output if it ever silently fails. A transient error that never clears
    must still fall through to the function's own pre-existing (s, None)
    degradation quickly, not hang or retry forever."""
    fake = _FlakyTokenSession(fail_times=99)
    _patch_async_session(monkeypatch, fake)
    s, token = asyncio.run(b4a._get_session_and_token())
    assert fake.calls == 3   # stop_after_attempt(3), then the outer except catches it
    assert token is None
    assert s is fake


def test_get_session_and_token_real_http_error_status_is_not_retried(monkeypatch):
    fake = _FlakyTokenSession(fail_times=0, resp=_FakeResp(status_code=503, text=""))
    _patch_async_session(monkeypatch, fake)
    s, token = asyncio.run(b4a._get_session_and_token())
    assert fake.calls == 1   # a real bad status is not a transport/timeout error
    assert token is None
