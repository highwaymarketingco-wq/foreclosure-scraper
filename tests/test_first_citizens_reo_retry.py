"""first_citizens_reo.py: a transient transport/timeout error on either of
this file's two real network call sites gets retried, not treated as "the
whole scrape failed."

Found 2026-11-07 (bug-shape sweep, same root cause already fixed tonight for
a Column legal-notice API scraper, spartan_weekly_legals.py, the shared
arcgis_webmap.query_features() function, and (also curl_cffi-based)
bid4assets.py / richland_flc.py): neither of this file's two network calls --
_fetch_json_text's primary curl-cffi JSON fetch, nor _render_html's fallback
Scrapling/Playwright headless render -- had any retry cushioning at all. A
single transient blip on the cheap primary call unconditionally forced the
far more expensive browser-render fallback every time, and a blip on THAT
(which also had zero retries) silently zeroed the whole run. Because this
source is registered in main.DATELESS_OK_SOURCES (no fallback date window), a
zeroed run reports as a healthy empty result with no self-heal.

Nuance (why this file needed its own, not a copy-paste, fix): unlike the
httpx-based fixes above, this file rolls curl_cffi.requests (`cf.get`)
directly for its primary path and Scrapling's StealthyFetcher for its
fallback -- confirmed in this project's venv (curl_cffi 0.15.0, scrapling
0.4.8) -- so the retry predicates below target THOSE libraries' own
transport/timeout exception types (curl_cffi.requests.exceptions for site 1,
playwright.sync_api for site 2), not httpx.TransportError/TimeoutException,
which neither library ever raises. AND -- unlike every other scraper fixed
tonight -- both of this file's vulnerable calls live inside a plain SYNC
`_sync()` closure dispatched via `asyncio.to_thread` (because curl_cffi's
plain `.get()` and StealthyFetcher's plain `.fetch()` are both blocking
calls), not inside a coroutine that `await`s directly. `async for attempt in
AsyncRetrying(...)` is a SyntaxError outside an async function, so the fix
uses tenacity's synchronous `Retrying` (`for attempt in Retrying(...): with
attempt: ...`) instead -- the same stop/wait/retry/reraise configuration,
adapted to run inside a worker thread with no event loop of its own.

Mirrors the fakes/structure of test_bid4assets_retry.py (curl_cffi) and
test_sc_public_index_lis_pendens_retry.py (Playwright/Scrapling), adapted
from async mocks to plain sync callables since both of THIS file's call
sites are sync (see above).
"""
from __future__ import annotations

import asyncio

import pytest
from curl_cffi.requests.exceptions import ConnectTimeout as CurlConnectTimeout
from curl_cffi.requests.exceptions import HTTPError as CurlHTTPError
from curl_cffi.requests.exceptions import ReadTimeout as CurlReadTimeout
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from scrapling.fetchers import StealthyFetcher
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from foreclosure_scraper.scrapers.national import first_citizens_reo as fcr

JSON_URL = "https://www.firstcitizens.test/real-estate.json"
RENDER_URL = "https://www.firstcitizens.test/real-estate"

# A real-shaped JSON body > 20 chars, matching _fetch_json_text's own
# content-validity check (status_code == 200 and len(r.text) > 20).
_REAL_JSON_TEXT = '{"realEstateData": [{"city": "Wilmington", "state": "NC"}]}'


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Make the exponential-jitter backoff effectively instant for tests."""
    monkeypatch.setattr(
        fcr, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


# ---------------------------------------------------------------------------
# _fetch_json_text -- the primary curl-cffi JSON fetch (cf.get(...))
# ---------------------------------------------------------------------------

class _FakeResp:
    """Mimics the curl_cffi.requests Response object's two attributes this
    call site reads."""

    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _FlakyGet:
    """Stands in for curl_cffi's module-level `cf.get` -- raises on the first
    `fail_times` calls, then returns a real (terminal) response. A plain SYNC
    callable (not async): _fetch_json_text's `cf.get(...)` call runs inside a
    plain sync closure dispatched via asyncio.to_thread, never awaited."""

    def __init__(self, fail_times: int, exc=None, resp: _FakeResp | None = None):
        self.fail_times = fail_times
        self.exc = exc or CurlConnectTimeout("boom")
        self.resp = resp if resp is not None else _FakeResp(status_code=200, text=_REAL_JSON_TEXT)
        self.calls = 0

    def __call__(self, url, impersonate=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.resp


def test_fetch_json_text_retries_a_transient_connect_timeout_and_then_succeeds(monkeypatch):
    """(a): a transient transport/timeout error on the primary JSON fetch is
    retried, and the retried request's real data comes through -- not
    silently dropped as an empty string."""
    fake = _FlakyGet(fail_times=2)
    monkeypatch.setattr(fcr.cf, "get", fake)

    out = asyncio.run(fcr._fetch_json_text(JSON_URL))

    assert fake.calls == 3
    assert out == _REAL_JSON_TEXT


def test_fetch_json_text_a_read_timeout_is_also_retried(monkeypatch):
    """A sibling transient type (ReadTimeout, not just ConnectTimeout) is
    retried too -- the predicate isn't accidentally narrowed to one class."""
    fake = _FlakyGet(fail_times=1, exc=CurlReadTimeout("slow"))
    monkeypatch.setattr(fcr.cf, "get", fake)

    out = asyncio.run(fcr._fetch_json_text(JSON_URL))

    assert fake.calls == 2
    assert out == _REAL_JSON_TEXT


def test_fetch_json_text_transient_timeout_that_never_clears_stops_after_budget_not_hangs(monkeypatch):
    """(b), integrated: a transient error that never clears must still fall
    through to _fetch_json_text's own pre-existing except-and-return-""
    quickly (unchanged by this fix), not hang or retry forever."""
    fake = _FlakyGet(fail_times=99)
    monkeypatch.setattr(fcr.cf, "get", fake)

    out = asyncio.run(fcr._fetch_json_text(JSON_URL))

    assert fake.calls == 3   # stop_after_attempt(3), then the outer except catches it
    assert out == ""


def test_fetch_json_text_real_bad_status_is_not_retried(monkeypatch):
    """(c), integrated: a real non-transport HTTP status (and, separately, a
    too-short body) is a content decision, not a transport failure -- it
    must fail immediately on attempt 1. The response comes back from
    cf.get() WITHOUT raising (curl_cffi never auto-raises on a bad status),
    so the retry predicate -- which only fires on an exception -- is never
    even consulted."""
    fake = _FlakyGet(fail_times=0, resp=_FakeResp(status_code=503, text="server error"))
    monkeypatch.setattr(fcr.cf, "get", fake)

    out = asyncio.run(fcr._fetch_json_text(JSON_URL))

    assert fake.calls == 1   # a real bad status is not a transport/timeout error
    assert out == ""


def test_fetch_json_text_too_short_body_is_not_retried(monkeypatch):
    """The OTHER half of the same content-validity check: a 200 with a body
    too short to be real data (len(text) <= 20) must also resolve on attempt
    1, never retried -- it's a content decision, the exact nuance called out
    in this file's module docstring."""
    fake = _FlakyGet(fail_times=0, resp=_FakeResp(status_code=200, text="{}"))
    monkeypatch.setattr(fcr.cf, "get", fake)

    out = asyncio.run(fcr._fetch_json_text(JSON_URL))

    assert fake.calls == 1
    assert out == ""


def test_transient_exc_tuple_retries_then_raises_when_budget_exhausted():
    """(b), at the primitive level: the exact predicate _fetch_json_text's
    call site uses (fcr._TRANSIENT_EXC) really does raise once
    stop_after_attempt(3) is exhausted against a persistently transient
    curl_cffi error -- not an infinite retry loop/hang. Driven directly
    against tenacity's sync Retrying (not AsyncRetrying -- see module
    docstring), independent of _fetch_json_text's own outer catch-all."""
    calls = {"n": 0}

    def _drive():
        for attempt in Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.001, max=0.002),
            retry=retry_if_exception_type(fcr._TRANSIENT_EXC),
            reraise=True,
        ):
            with attempt:
                calls["n"] += 1
                raise CurlConnectTimeout("boom")

    with pytest.raises(CurlConnectTimeout):
        _drive()
    assert calls["n"] == 3


def test_transient_exc_tuple_does_not_include_http_error():
    """(c), predicate-level: curl_cffi's HTTPError must never be treated as
    transient -- this call site never calls .raise_for_status() (status is
    checked manually), but the predicate itself must stay scoped to
    transport/timeout only, not any error curl_cffi can raise."""
    assert not issubclass(CurlHTTPError, fcr._TRANSIENT_EXC)


# ---------------------------------------------------------------------------
# _render_html -- the fallback Scrapling/Playwright headless render
# (StealthyFetcher.fetch(...))
# ---------------------------------------------------------------------------

class _FakePage:
    """Mimics the Scrapling ``Response`` object's one attribute this call
    site reads."""

    def __init__(self, html_content: str):
        self.html_content = html_content


class _FlakyFetch:
    """Stands in for StealthyFetcher.fetch -- raises on the first
    `fail_times` calls, then returns a real (terminal) page. A plain SYNC
    callable (not async): _render_html's `StealthyFetcher.fetch(...)` call
    runs inside a plain sync closure dispatched via asyncio.to_thread, never
    awaited (unlike every other Playwright/Scrapling fix tonight, which
    wraps the ASYNC `StealthyFetcher.async_fetch` instead)."""

    def __init__(self, fail_times: int, exc: Exception | None = None,
                 html: str = "<table>real page</table>"):
        self.fail_times = fail_times
        self.exc = exc or PlaywrightError("net::ERR_CONNECTION_RESET")
        self.html = html
        self.calls = 0

    def __call__(self, url, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakePage(self.html)


class _AlwaysFailsFetch:
    """Raises the same exception on every call -- never clears."""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    def __call__(self, url, **kwargs):
        self.calls += 1
        raise self.exc


def test_render_html_retries_a_transient_playwright_error_and_then_succeeds(monkeypatch):
    """(a): a transient Playwright/Scrapling connection error on the
    fallback render is retried, and the retried render's real HTML comes
    through -- not silently dropped as an empty string."""
    fake = _FlakyFetch(fail_times=2)
    monkeypatch.setattr(StealthyFetcher, "fetch", fake)

    out = asyncio.run(fcr._render_html(RENDER_URL))

    assert fake.calls == 3
    assert out == "<table>real page</table>"


def test_render_html_a_playwright_timeout_error_is_also_retried(monkeypatch):
    """The other listed transient type (TimeoutError, a subclass of Error)
    is honored too -- a navigation-timeout failure, not just a raw
    connection error."""
    fake = _FlakyFetch(fail_times=1, exc=PlaywrightTimeoutError("Timeout 45000ms exceeded"))
    monkeypatch.setattr(StealthyFetcher, "fetch", fake)

    out = asyncio.run(fcr._render_html(RENDER_URL))

    assert fake.calls == 2
    assert out == "<table>real page</table>"


def test_render_html_transient_error_that_never_clears_stops_after_budget_not_hangs(monkeypatch):
    """(b), integrated: _render_html's pre-existing outer try/except is
    untouched -- it still returns "" on an ultimately-unrecoverable failure
    rather than raising to its caller. What the fix adds is that this now
    happens only after stop_after_attempt(3) is exhausted, not on the first
    blip, and it terminates promptly instead of hanging."""
    fake = _AlwaysFailsFetch(PlaywrightError("net::ERR_CONNECTION_RESET"))
    monkeypatch.setattr(StealthyFetcher, "fetch", fake)

    out = asyncio.run(fcr._render_html(RENDER_URL))

    assert fake.calls == 3   # stop_after_attempt(3), then gives up -- no infinite retry
    assert out == ""


def test_render_html_a_real_non_transient_error_is_not_retried(monkeypatch):
    """(c), adapted: this render path has no HTTP-status concept at all (a
    bad server response doesn't make page.goto() raise) -- so the faithful
    equivalent of "a real non-transport error is not retried" is a genuine
    non-network failure (e.g. a scrapling/Playwright config bug surfaced as
    a plain ValueError, not a Playwright transport or timeout error), which
    must fail immediately on attempt 1 exactly like before this fix.
    Retrying it would just waste time re-launching a whole headless-browser
    render on a failure that will never clear."""
    fake = _AlwaysFailsFetch(ValueError("Argument `selector_config` must be a dictionary."))
    monkeypatch.setattr(StealthyFetcher, "fetch", fake)

    out = asyncio.run(fcr._render_html(RENDER_URL))

    assert fake.calls == 1   # a real non-transport/timeout error is not retried
    assert out == ""
