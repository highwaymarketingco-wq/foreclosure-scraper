"""national.nc_unclaimed._fetch_with_playwright: the per-surname POST to
unclaimed.nccash.gov's /SWS/properties API gets transport/timeout retry
cushioning, not a bare httpx.AsyncClient() with zero retry protection.

Found 2026-11-07, the same bug shape already fixed tonight in this repo for
arcgis_webmap.query_features and spartan_weekly_legals.py: the Turnstile-token
flow ends in `async with httpx.AsyncClient() as client: for surname in
surnames: resp = await client.post(...)` -- a bare client with no retry
wrapper at all, and a per-surname `except Exception` as its only net. A
transient transport blip (connection reset, read timeout) on one surname
falls straight into that except, which writes an "error" entry into the
searched ledger for that surname -- and because _candidate_surnames() skips
any surname already present in the ledger regardless of whether the prior
attempt succeeded, got a bad status, or merely errored, one network blip
would otherwise permanently exclude that surname from every future run, not
just this one (the ledger has no concept of "retry me later").

_fetch_with_playwright() is not architected for dependency injection the way
spartan_weekly_legals._row_to_listing() is -- its httpx client is created
internally, after a full Playwright/Turnstile flow with no earlier injection
point -- so this test drives the REAL method end to end with a minimal fake
Playwright chain (just enough to reach a captured token and fall through to
the httpx loop) plus a monkeypatched httpx.AsyncClient whose .post() is what
each test actually controls. None of the Playwright scaffolding below is what
the fix is about; it exists only because the retry-wrapped call sits
downstream of it in the same method.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import nc_unclaimed as mod

_TOKEN = "FAKE_TURNSTILE_TOKEN_1234567890"  # len > 10 is the only check the real code makes


# --------------------------------------------------------------------------- #
# Minimal fake Playwright chain -- walks goto -> wait_for_function ->
# evaluate(token) straight through to the httpx loop below.
# --------------------------------------------------------------------------- #

class _FakePage:
    def __init__(self, token):
        self.frames = []  # empty -> the checkbox-click branch is skipped entirely
        self._token = token

    def on(self, *a, **kw):
        pass

    async def goto(self, *a, **kw):
        pass

    async def wait_for_function(self, *a, **kw):
        pass

    async def evaluate(self, *a, **kw):
        # Valid on the very first call, so the turnstile loop's
        # "if token and len(token) > 10: break" fires immediately -- none of
        # its own internal sleeps/attempts run.
        return self._token


class _FakeContext:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page


class _FakeBrowser:
    def __init__(self, ctx):
        self._ctx = ctx

    async def new_context(self, **kw):
        return self._ctx

    async def close(self):
        pass


class _FakeChromium:
    def __init__(self, browser):
        self._browser = browser

    async def launch(self, **kw):
        return self._browser


class _FakePlaywrightCM:
    """`async_playwright()` returns this; `async with ... as pw:` then hands
    back the fake `pw` whose .chromium.launch() walk reaches `_FakePage`."""

    def __init__(self, pw):
        self._pw = pw

    async def __aenter__(self):
        return self._pw

    async def __aexit__(self, *exc):
        return False


def _install_fake_playwright(monkeypatch, token=_TOKEN):
    page = _FakePage(token)
    ctx = _FakeContext(page)
    browser = _FakeBrowser(ctx)
    chromium = _FakeChromium(browser)
    pw = SimpleNamespace(chromium=chromium)
    # `from patchright.async_api import async_playwright` is a LOCAL import
    # inside _fetch_with_playwright, resolved at call time -- patching the
    # real module attribute before that call is what redirects it here.
    monkeypatch.setattr("patchright.async_api.async_playwright",
                        lambda: _FakePlaywrightCM(pw))


# --------------------------------------------------------------------------- #
# Fake httpx -- THIS is what each test actually drives.
# --------------------------------------------------------------------------- #

class _FakeResp:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class _FlakyHttp:
    """Raises on the first N-1 .post() calls, then serves a real 200 response
    carrying one unclaimed-property row."""

    def __init__(self, fail_times: int, exc: Exception | None = None):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls = 0

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResp({"items": [
            {"ownerName": "TESTSURNAME, J", "address": "1 Test Ln", "amount": "123.45"},
        ]})


def _install_fake_async_client(monkeypatch, fake_http):
    class _CM:
        async def __aenter__(self):
            return fake_http

        async def __aexit__(self, *exc):
            return False

    # The real call site is `async with httpx.AsyncClient() as client:` --
    # zero constructor args -- so this stands in for the class itself.
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _CM())


# --------------------------------------------------------------------------- #
# Fixtures shared by every test below
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


@pytest.fixture(autouse=True)
def _no_real_sleeps(monkeypatch):
    """_fetch_with_playwright() has its own unconditional `await
    asyncio.sleep(8)` right after page.goto() (waiting for the real Angular
    SPA to settle) -- unrelated to the retry fix under test, but it still
    runs on every call. Neutralized here rather than paying 8+ real seconds
    per test; this is the real `asyncio` module, so it also covers the local
    `import asyncio` inside the method under test (same module object)."""
    async def _instant(*a, **kw):
        return None
    monkeypatch.setattr(asyncio, "sleep", _instant)


@pytest.fixture(autouse=True)
def _isolate_board_and_ledger(monkeypatch, tmp_path):
    """One deterministic surname, and the searched-ledger write redirected
    off the real repo file -- same isolation test_nc_unclaimed_real_surnames.py
    already uses for _SEARCHED_LEDGER_PATH."""
    monkeypatch.setattr(mod, "_candidate_surnames", lambda: ["TESTSURNAME"])
    monkeypatch.setattr(mod, "_SEARCHED_LEDGER_PATH", tmp_path / "nc_unclaimed_searched.json")


@pytest.fixture(autouse=True)
def _fake_playwright(monkeypatch):
    _install_fake_playwright(monkeypatch)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_a_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    http = _FlakyHttp(fail_times=2)
    _install_fake_async_client(monkeypatch, http)

    scraper = mod.NcUnclaimedScraper()
    results = asyncio.run(scraper._fetch_with_playwright())

    assert http.calls == 3
    # Proves the retried POST's response was actually fetched and parsed,
    # not just that the call didn't raise.
    assert len(results) == 1
    assert results[0].owner_name == "TESTSURNAME, J"


def test_a_read_timeout_is_also_retried(monkeypatch):
    http = _FlakyHttp(fail_times=1, exc=httpx.ReadTimeout("slow"))
    _install_fake_async_client(monkeypatch, http)

    scraper = mod.NcUnclaimedScraper()
    results = asyncio.run(scraper._fetch_with_playwright())

    assert http.calls == 2
    assert len(results) == 1


def test_a_connect_timeout_that_never_clears_gives_up_not_hangs(monkeypatch, tmp_path):
    http = _FlakyHttp(fail_times=99)
    _install_fake_async_client(monkeypatch, http)

    scraper = mod.NcUnclaimedScraper()
    results = asyncio.run(scraper._fetch_with_playwright())

    assert http.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite retry loop
    assert results == []     # nothing succeeded for this surname

    # The per-surname `except Exception` (pre-existing, unrelated to this
    # fix) is what keeps one exhausted surname from aborting the whole run --
    # same non-fatal-per-item contract as every sibling *_retry.py test in
    # this repo. Confirm the exhausted retry actually surfaced as a recorded
    # error, not a silent drop.
    ledger = json.loads((tmp_path / "nc_unclaimed_searched.json").read_text())
    assert "error" in ledger["surnames"]["testsurname"]


def test_a_real_http_error_status_is_not_retried(monkeypatch, tmp_path):
    class _BadStatusHttp:
        def __init__(self):
            self.calls = 0

        async def post(self, url, json=None, headers=None, timeout=None):
            self.calls += 1
            return _FakeResp({}, status_code=503)

    http = _BadStatusHttp()
    _install_fake_async_client(monkeypatch, http)

    scraper = mod.NcUnclaimedScraper()
    results = asyncio.run(scraper._fetch_with_playwright())

    assert http.calls == 1   # a real bad status is not a transport/timeout error
    assert results == []

    ledger = json.loads((tmp_path / "nc_unclaimed_searched.json").read_text())
    assert ledger["surnames"]["testsurname"]["status"] == 503
