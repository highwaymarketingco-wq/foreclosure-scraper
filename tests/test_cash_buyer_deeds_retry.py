"""national.cash_buyer_deeds -- _cott_recent/_logan_recent's raw network calls get
transport/timeout retry cushioning, not a bare try/except swallowing straight to [].

Found 2026-11-07 (gap-sweep): both vendor-dispatch functions in this module open
their own httpx session via http_client.client() (a LOCAL `from ...http_client
import client as _client` -- that module's own docstring says callers must wrap
their own retries) and then make several sequential raw calls with zero
AsyncRetrying anywhere:

  * _logan_recent (McDowell/Transylvania/Mitchell -- the live, currently-working
    path): GET {host}/index.php, POST {host}/index.php to mint a search token,
    POST {host}/content.php?{token} with the real search body -- three calls, one
    bare `try` / `except Exception: return []` wrapping all of them.
  * _cott_recent (Polk/Rutherford -- currently inert for an unrelated, already-
    documented reason, see the function's own docstring, but the retry gap is
    structurally identical): GET {base}/SrchName.aspx, POST {base}/SrchName.aspx
    with the search form -- same bare-except pattern.

A single transient transport blip on ANY of these five calls used to be
swallowed whole by the surrounding bare except and converted to a plain `[]` --
indistinguishable from a genuinely quiet county/month -- and because this
scraper is registered in main.DATELESS_OK_SOURCES (no fallback date window)
that zero could not self-heal on a later run either. Same root cause already
fixed tonight for arcgis_webmap.query_features() and spartan_weekly_legals.py.
This file proves each of the five call sites now gets its own 3-attempt
AsyncRetrying budget (transport/timeout only, never a real bad HTTP status).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.national import cash_buyer_deeds as cbd


class _FakeResp:
    def __init__(self, text: str = "", status_code: int = 200):
        self.text = text
        self.status_code = status_code


class _LoganFlakyClient:
    """Simulates _logan_recent's three-call session:

        GET  {host}/index.php            -- the search form (return value unused)
        POST {host}/index.php            -- mints the search token
        POST {host}/content.php?{token}  -- the real search submission

    `site` picks ONE of "get_form" / "post_token" / "post_search" to misbehave;
    every other call site always succeeds on its first try. `calls` counts
    invocations of the TARGETED site only, so a test can assert exactly how many
    attempts that one retry loop made.

    Two independent failure modes, matching test_arcgis_webmap_query_features_retry.py's
    _FlakyHttp / _BadStatusHttp split:
      * `exc` + `fail_times` -- raise `exc` on the first `fail_times` calls to the
        targeted site, then serve a real response (or never recover, if
        `fail_times` is large -- proves the retry budget is bounded).
      * `always_bad_status` -- never raise; always return that HTTP status for
        the targeted site (a real, non-transport failure that must NOT retry).
    """

    def __init__(self, site: str, *, fail_times: int = 0,
                 exc: Exception | None = None,
                 always_bad_status: int | None = None,
                 token: str = "4242", sweep_html: str = ""):
        assert site in ("get_form", "post_token", "post_search")
        self.site = site
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.always_bad_status = always_bad_status
        self.token = token
        self.sweep_html = sweep_html
        self.calls = 0

    def _hit(self, this_site: str) -> _FakeResp | None:
        if this_site != self.site:
            return None
        self.calls += 1
        if self.always_bad_status is not None:
            return _FakeResp("", self.always_bad_status)
        if self.calls <= self.fail_times:
            raise self.exc
        return None

    async def get(self, url, **kw):
        bad = self._hit("get_form")
        return bad if bad is not None else _FakeResp("<html></html>")

    async def post(self, url, **kw):
        if "content.php" in url:
            bad = self._hit("post_search")
            return bad if bad is not None else _FakeResp(self.sweep_html)
        bad = self._hit("post_token")
        return bad if bad is not None else _FakeResp(f"go to content.php?{self.token}")


class _CottFlakyClient:
    """Simulates _cott_recent's two-call session:

        GET  {base}/SrchName.aspx -- serves the search form (__VIEWSTATE etc.)
        POST {base}/SrchName.aspx -- the real search submission

    Same single-targeted-site convention as `_LoganFlakyClient` above.
    """

    #: No login-gate markers; carries the literal "__VIEWSTATE" substring so
    #: _cott_recent's own fetch-failure guard
    #: (`if not viewstate and "__VIEWSTATE" not in html`) does not bail out
    #: before ever reaching the search POST this test targets.
    _FORM_HTML = '<html><input name="__VIEWSTATE" value=""></html>'

    def __init__(self, site: str, *, fail_times: int = 0,
                 exc: Exception | None = None,
                 always_bad_status: int | None = None, grid_html: str = ""):
        assert site in ("get_form", "post_search")
        self.site = site
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.always_bad_status = always_bad_status
        self.grid_html = grid_html
        self.calls = 0

    def _hit(self, this_site: str) -> _FakeResp | None:
        if this_site != self.site:
            return None
        self.calls += 1
        if self.always_bad_status is not None:
            return _FakeResp("", self.always_bad_status)
        if self.calls <= self.fail_times:
            raise self.exc
        return None

    async def get(self, url, **kw):
        bad = self._hit("get_form")
        return bad if bad is not None else _FakeResp(self._FORM_HTML)

    async def post(self, url, **kw):
        bad = self._hit("post_search")
        return bad if bad is not None else _FakeResp(self.grid_html)


def _patch_client(monkeypatch, fake_client) -> None:
    """Both _cott_recent and _logan_recent resolve `client` via a LOCAL import
    inside the function body (`from ...http_client import client as _client`),
    so the only effective patch point is the real attribute on the http_client
    module itself -- matching this module's own existing tests
    (test_cash_buyer_deeds.py's `_patch_http_client`,
    test_cash_buyer_deeds_logan_image.py's `_patch_logan_client`)."""
    import foreclosure_scraper.http_client as http_client_mod

    @asynccontextmanager
    async def _fake_client_cm(**kw):
        yield fake_client

    monkeypatch.setattr(http_client_mod, "client", _fake_client_cm)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(cbd, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# --------------------------------------------------------------------------- #
# (a) a transient transport/timeout error is retried and then succeeds --
#     proven independently at EACH of the five call sites this fix touches.
# --------------------------------------------------------------------------- #

def test_logan_get_form_retries_a_connect_timeout_then_succeeds(monkeypatch):
    fake = _LoganFlakyClient("get_form", fail_times=2)
    _patch_client(monkeypatch, fake)
    docs = asyncio.run(cbd._logan_recent("NC", "McDowell", 30))
    assert fake.calls == 3
    assert docs == []  # empty sweep_html -> no rows, but the session ran to completion


def test_logan_post_token_retries_a_connect_timeout_then_succeeds(monkeypatch):
    fake = _LoganFlakyClient("post_token", fail_times=2)
    _patch_client(monkeypatch, fake)
    docs = asyncio.run(cbd._logan_recent("NC", "McDowell", 30))
    assert fake.calls == 3
    assert docs == []


def test_logan_post_search_retries_a_connect_timeout_then_succeeds(monkeypatch):
    fake = _LoganFlakyClient("post_search", fail_times=2)
    _patch_client(monkeypatch, fake)
    docs = asyncio.run(cbd._logan_recent("NC", "McDowell", 30))
    assert fake.calls == 3
    assert docs == []


def test_logan_post_search_retries_a_read_timeout_too(monkeypatch):
    fake = _LoganFlakyClient("post_search", fail_times=1, exc=httpx.ReadTimeout("slow"))
    _patch_client(monkeypatch, fake)
    docs = asyncio.run(cbd._logan_recent("NC", "McDowell", 30))
    assert fake.calls == 2
    assert docs == []


def test_cott_get_form_retries_a_connect_timeout_then_succeeds(monkeypatch):
    fake = _CottFlakyClient("get_form", fail_times=2)
    _patch_client(monkeypatch, fake)
    docs = asyncio.run(cbd._cott_recent("NC", "Polk", 30))
    assert fake.calls == 3
    assert docs == []


def test_cott_post_search_retries_a_connect_timeout_then_succeeds(monkeypatch):
    fake = _CottFlakyClient("post_search", fail_times=2)
    _patch_client(monkeypatch, fake)
    docs = asyncio.run(cbd._cott_recent("NC", "Polk", 30))
    assert fake.calls == 3
    assert docs == []


# --------------------------------------------------------------------------- #
# (b) a transient error that NEVER clears still gives up after the retry
#     budget (stop_after_attempt(3)) -- not an infinite hang. The surrounding
#     bare except (pre-existing, unrelated to this fix) swallows the exhausted
#     retry into a plain [], the same non-fatal-per-county contract as every
#     other failure path in this scraper.
# --------------------------------------------------------------------------- #

def test_logan_post_search_gives_up_after_three_attempts_not_hangs(monkeypatch):
    fake = _LoganFlakyClient("post_search", fail_times=99)
    _patch_client(monkeypatch, fake)
    docs = asyncio.run(cbd._logan_recent("NC", "McDowell", 30))
    assert fake.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite retry loop
    assert docs == []        # bare except converts the exhausted retry; doesn't hang or crash


def test_cott_post_search_gives_up_after_three_attempts_not_hangs(monkeypatch):
    fake = _CottFlakyClient("post_search", fail_times=99)
    _patch_client(monkeypatch, fake)
    docs = asyncio.run(cbd._cott_recent("NC", "Polk", 30))
    assert fake.calls == 3
    assert docs == []


# --------------------------------------------------------------------------- #
# (c) a real non-transport HTTP error status is NOT retried -- the response
#     completes normally (no exception raised), so AsyncRetrying never even
#     sees it, and the call site's own pre-existing `if status != 200:
#     return []` check (unchanged by this fix) is what actually handles it.
#     Exactly one attempt, every time -- never recovers, so a future
#     regression that wrongly retried bad statuses would show up here too.
# --------------------------------------------------------------------------- #

def test_logan_post_search_real_bad_status_is_not_retried(monkeypatch):
    fake = _LoganFlakyClient("post_search", always_bad_status=503)
    _patch_client(monkeypatch, fake)
    docs = asyncio.run(cbd._logan_recent("NC", "McDowell", 30))
    assert fake.calls == 1   # a real bad status is not a transport/timeout error
    assert docs == []


def test_cott_post_search_real_bad_status_is_not_retried(monkeypatch):
    fake = _CottFlakyClient("post_search", always_bad_status=503)
    _patch_client(monkeypatch, fake)
    docs = asyncio.run(cbd._cott_recent("NC", "Polk", 30))
    assert fake.calls == 1
    assert docs == []
