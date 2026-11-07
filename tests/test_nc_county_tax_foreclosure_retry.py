"""nc_county_tax_foreclosure._render: a transient empty render result gets retried,
not treated as "this county's sale page has zero rows this run."

fetch_rendered() (foreclosure_scraper.render) swallows every network,
browser-launch, timeout, and bad-status error internally and always returns ""
on failure -- it never raises for this caller, since _render() never passes
raise_on_http_failure=True. That means the exception-keyed AsyncRetrying
pattern used elsewhere in this codebase (the Column legal-notice API,
spartan_weekly_legals.py, arcgis_webmap.query_features()) would compile here
but never actually fire: no exception of any type ever escapes
fetch_rendered() for _render() to retry on. The real retryable signal for this
call is a falsy (empty-string) result, so _render() retries on that instead,
via tenacity's retry_if_result -- these tests pin that behavior directly.
"""
from __future__ import annotations

import asyncio

import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper import render as render_module
from foreclosure_scraper.scrapers.counties_nc import nc_county_tax_foreclosure as nctf

URL = "https://example.test/tax-foreclosures"


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(
        nctf, "wait_exponential_jitter",
        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002),
    )


class _FlakyRender:
    """Returns "" (fetch_rendered's own on-failure value) on the first
    ``fail_times`` calls, then a real page on every call after that."""

    def __init__(self, fail_times: int, text: str = "<html>25 M 388</html>"):
        self.fail_times = fail_times
        self.text = text
        self.calls = 0

    async def __call__(self, url: str) -> str:
        self.calls += 1
        if self.calls <= self.fail_times:
            return ""
        return self.text


class _RaisingRender:
    """Simulates an exception escaping fetch_rendered. Not its documented
    contract today (it always catches internally and returns ""), but
    _render()'s own bare except must still swallow this to "" on the very
    first attempt, without retrying -- retry_if_result does not retry on a
    failed/exception outcome, only on a falsy *result*."""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    async def __call__(self, url: str) -> str:
        self.calls += 1
        raise self.exc


def test_a_transient_empty_render_is_retried_and_then_succeeds(monkeypatch):
    fake = _FlakyRender(fail_times=2)
    monkeypatch.setattr(render_module, "fetch_rendered", fake)
    result = asyncio.run(nctf._render(URL))
    assert fake.calls == 3
    assert result == "<html>25 M 388</html>"


def test_an_empty_render_that_never_clears_still_returns_empty_not_hangs(monkeypatch):
    fake = _FlakyRender(fail_times=99)
    monkeypatch.setattr(render_module, "fetch_rendered", fake)
    result = asyncio.run(nctf._render(URL))
    assert fake.calls == 3   # stop_after_attempt(3), then gives up -- never an infinite retry
    assert result == ""      # _render's documented on-failure contract, preserved


def test_a_real_exception_is_not_retried(monkeypatch):
    fake = _RaisingRender(RuntimeError("camoufox blew up"))
    monkeypatch.setattr(render_module, "fetch_rendered", fake)
    result = asyncio.run(nctf._render(URL))
    assert fake.calls == 1    # an exception outcome is not retried by retry_if_result
    assert result == ""


def test_a_clean_first_render_needs_no_retry(monkeypatch):
    fake = _FlakyRender(fail_times=0, text="<html>clean</html>")
    monkeypatch.setattr(render_module, "fetch_rendered", fake)
    result = asyncio.run(nctf._render(URL))
    assert fake.calls == 1
    assert result == "<html>clean</html>"
