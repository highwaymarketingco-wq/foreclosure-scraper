"""counties_sc.sc_probate_net._search_county: a transient transport/timeout error on
any of the four GET/POST postback calls gets retried, not treated as "this whole
(county, surname) sweep's result set is gone."

Found 2026-11-07 (same sweep as the Column legal-notice API scraper /
spartan_weekly_legals.py / arcgis_webmap.query_features() fixes): the shared
httpx.AsyncClient built directly in SCProbateNet.fetch() carries no retry cushioning
of its own (http_client.client()'s own docstring says callers must wrap their own),
and all four real network calls in _search_county() -- the step-1 form GET, the
step-2 county-change postback, the step-3 search postback, and the pager postback
inside the `while page < MAX_GRID_PAGES` loop -- were bare httpx calls with zero
retry wrapper. fetch() wraps each _search_county() call in a bare
`except httpx.HTTPError: log.warning(...); continue`, which is a skip-and-log, not a
retry: a single connection reset/timeout on ANY of those four calls used to silently
drop that entire surname/county's estates for the run (live-verified elsewhere in
this module's own docstring: a Charleston Probate "Smith" sweep returns 98 estates
across 5 pages -- one mid-sweep blip loses all of them, logged only as a WARNING).
Markup below is minimal and invented; the parsers are irrelevant to what is under
test here, which is the retry behavior around each network call.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import sc_probate_net as m

PRE = m.PRE
GRID = PRE + "cgvCases"  # non-marriage grid name used by the pager postback


def _html(viewstate: str, extra: str = "") -> str:
    return f'<html><body><input type="hidden" name="__VIEWSTATE" value="{viewstate}">{extra}</body></html>'


# Step-3 search response: no actual cgvCases table (so _parse_probate's early
# `grid is None` branch returns [] with no further parsing needed), but WITH a
# pager link to Page$2 so the while loop in _search_county() follows it.
_SEARCH_PAGE1_WITH_PAGER = _html(
    "vs-search",
    f"<a href=\"javascript:__doPostBack(&#39;{GRID}&#39;,&#39;Page$2&#39;)\">2</a>",
)
# Pager response (page 2): no further Page$3 link, so the loop stops after one hop.
_PAGER_PAGE2_TERMINAL = _html("vs-page2")


class _Resp:
    """Fake httpx.Response: carries .text/.status_code and raises a real
    httpx.HTTPStatusError from .raise_for_status() for a bad status, exactly
    like the real response object the retried code calls raise_for_status() on."""

    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", m.BASE_URL)
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=response
            )


class _FlakyClient:
    """Fake httpx.AsyncClient standing in for the one SCProbateNet.fetch() builds.

    Keyed by STEP, not by raw call ordinal, because a retry re-issues the exact
    same logical call (e.g. the step-3 search postback) several times -- `calls`
    counts attempts per step so a test can assert "retried N times then succeeded"
    without the retry's own re-invocations being mistaken for the next distinct
    step in the sequence. The step for a POST is read off __EVENTTARGET, exactly
    how the real ASP.NET postback identifies which control fired it.
    """

    STEP_LOAD = "load"
    STEP_COUNTY_CHANGE = "county_change"
    STEP_SEARCH = "search"
    STEP_PAGER = "pager"

    def __init__(self, fail_step: str, fail_times: int, exc: Exception | None = None):
        self.fail_step = fail_step
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.calls: dict[str, int] = {}
        self.terminal_status: dict[str, int] = {}  # step -> status_code override

    def _responses(self) -> dict[str, str]:
        return {
            self.STEP_LOAD: _html("vs-load"),
            self.STEP_COUNTY_CHANGE: _html("vs-county"),
            self.STEP_SEARCH: _SEARCH_PAGE1_WITH_PAGER,
            self.STEP_PAGER: _PAGER_PAGE2_TERMINAL,
        }

    def _step_for_post(self, data: dict) -> str:
        target = (data or {}).get("__EVENTTARGET", "")
        if target == PRE + "ddlCounties":
            return self.STEP_COUNTY_CHANGE
        if target == PRE + "btnSearch":
            return self.STEP_SEARCH
        return self.STEP_PAGER  # the grid's own control name

    async def _respond(self, step: str) -> _Resp:
        self.calls[step] = self.calls.get(step, 0) + 1
        if step == self.fail_step and self.calls[step] <= self.fail_times:
            raise self.exc
        status = self.terminal_status.get(step, 200)
        return _Resp(self._responses()[step], status_code=status)

    async def get(self, url, **kw):
        return await self._respond(self.STEP_LOAD)

    async def post(self, url, data=None, **kw):
        return await self._respond(self._step_for_post(data or {}))


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Same trick as the arcgis_webmap reference test: replace the module's
    wait_exponential_jitter with a near-zero-wait version so a retried test
    runs in milliseconds, not seconds."""
    monkeypatch.setattr(
        m, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )
    # The pager loop's own polite-pause sleep is unrelated to retry backoff;
    # zero it too so pager-path tests don't pay GRID_PAGE_PAUSE_S real seconds.
    monkeypatch.setattr(m, "GRID_PAGE_PAUSE_S", 0)


def _run(client):
    return asyncio.run(
        m._search_county(client, "Charleston Probate", "Charleston", "SC", False, "Smith")
    )


# (a) a transient transport/timeout error is retried and then succeeds.

def test_a_transient_connect_timeout_on_search_postback_is_retried_and_then_succeeds():
    client = _FlakyClient(fail_step=_FlakyClient.STEP_SEARCH, fail_times=2)
    out = _run(client)
    assert client.calls[_FlakyClient.STEP_SEARCH] == 3
    assert out == []  # no real cgvCases table in the stub page -> parses to no rows


def test_a_read_timeout_on_the_initial_form_load_is_also_retried():
    client = _FlakyClient(
        fail_step=_FlakyClient.STEP_LOAD, fail_times=1, exc=httpx.ReadTimeout("slow"),
    )
    out = _run(client)
    assert client.calls[_FlakyClient.STEP_LOAD] == 2
    assert out == []


def test_a_transient_error_on_the_pager_postback_is_retried_and_the_next_page_still_reads():
    """The pager call (inside the `while page < MAX_GRID_PAGES` loop) is the call
    site with the largest real blast radius per the investigation (a 25-page x
    20-row grid) -- proven fixed on its own, not just inferred from the other
    three call sites sharing the same wrapper."""
    client = _FlakyClient(fail_step=_FlakyClient.STEP_PAGER, fail_times=2)
    out = _run(client)
    assert client.calls[_FlakyClient.STEP_PAGER] == 3
    # The pager was actually followed to page 2 (not abandoned after the blip).
    assert client.calls[_FlakyClient.STEP_SEARCH] == 1
    assert out == []


# (b) a transient error that never clears still raises after the retry budget is
# exhausted -- not an infinite hang.

def test_a_connect_timeout_that_never_clears_still_raises_not_hangs():
    client = _FlakyClient(fail_step=_FlakyClient.STEP_SEARCH, fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        _run(client)
    assert client.calls[_FlakyClient.STEP_SEARCH] == 3  # stop_after_attempt(3), then gives up


def test_a_transport_error_that_never_clears_on_the_pager_also_raises_not_hangs():
    client = _FlakyClient(fail_step=_FlakyClient.STEP_PAGER, fail_times=99)
    with pytest.raises(httpx.ConnectTimeout):
        _run(client)
    assert client.calls[_FlakyClient.STEP_PAGER] == 3


# (c) a real non-transport HTTP error status is NOT retried -- fails immediately on
# attempt 1.

def test_a_real_http_error_status_is_not_retried():
    client = _FlakyClient(fail_step=_FlakyClient.STEP_SEARCH, fail_times=0)
    client.terminal_status[_FlakyClient.STEP_SEARCH] = 503
    with pytest.raises(httpx.HTTPStatusError):
        _run(client)
    assert client.calls[_FlakyClient.STEP_SEARCH] == 1  # a real bad status is not a transport/timeout error


def test_a_real_http_error_status_on_the_initial_load_is_not_retried():
    client = _FlakyClient(fail_step=_FlakyClient.STEP_LOAD, fail_times=0)
    client.terminal_status[_FlakyClient.STEP_LOAD] = 500
    with pytest.raises(httpx.HTTPStatusError):
        _run(client)
    assert client.calls[_FlakyClient.STEP_LOAD] == 1
