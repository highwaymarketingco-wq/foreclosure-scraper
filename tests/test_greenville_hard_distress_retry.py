"""counties_sc.greenville_tax_distress (greenville_hard_distress.py): a transient
transport error on any of this module's three unprotected network calls gets
retried, not treated as "that call permanently failed."

Found via gap-sweep audit 2026-11-07 (same pattern already fixed tonight elsewhere
in this repo: a Column legal-notice API scraper, spartan_weekly_legals.py, the
shared arcgis_webmap.query_features(), and counties_sc.greenville_probate). Full
inventory of this file's six network call sites: fetch_delinquent_parcels(),
fetch_parcels_by_pin() and fetch_sales_by_pin() all route through
arcgis_webmap.query_features(), which already carries its own AsyncRetrying (dated
2026-10-16) -- confirmed by reading that function directly -- so they are not
bugs. The other three had zero retry cushioning at all:

  * fetch_tax_sale() -- a bare http.get(TAXSALE_URL). Runs in the DEFAULT-ENABLED
    path (FORECLOSURE_INCLUDE_GREENVILLE defaults to "1"). Its only caller, fetch(),
    wraps it in a try/except that catches ANY exception once (transient or not) and
    substitutes an empty TaxSaleParse rather than retrying -- a single transient
    blip silently zeroes the whole tax-sale-roster lane (and the `missing` list
    that drives fetch_parcels_by_pin's backfill) for the run.
  * probate_search() and collect_probate()'s own form-state GET have the identical
    unprotected shape, but sit behind the separate, off-by-default
    FORECLOSURE_GREENVILLE_PROBATE flag -- lower severity (probate is purely
    additive metadata; build_listing() never gates a listing on it), but the same
    bug shape and worth the same fix for consistency.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import greenville_hard_distress as mod

_REQ = httpx.Request("GET", "https://www.greenvillecounty.org/appsAS400/Taxsale/")

#: Same PIN used by the module's own fixture-backed tests (test_greenville_hard_distress.py),
#: so _normalize_parcel() is known to turn it into a real, non-empty pin.
_PIN = "0032000200610"

# A real, parseable, terminal tax-sale roster page: header row + one data row.
_TAXSALE_HTML = (
    "<table><tr><th>Item</th><th>Map#</th><th>Name</th><th>Amount</th></tr>"
    f"<tr><td>1</td><td>{_PIN}</td><td>JONES BOB</td><td>$500.00</td></tr></table>"
)

# A real, parseable, terminal probate search-results page with no matches.
_PROBATE_SEARCH_HTML = "<table><tr><th>Case</th><th>Name</th><th>Party</th></tr></table>"

# A real probate form page carrying the hidden ASP.NET state fields collect_probate()
# needs. Paired with an empty owners_by_surname so no probate_search() call follows.
_PROBATE_FORM_HTML = (
    '<input type="hidden" name="__VIEWSTATE" value="abc123">'
    '<input type="hidden" name="__VIEWSTATEGENERATOR" value="xyz">'
    '<input type="hidden" name="__EVENTVALIDATION" value="qrs">'
)


class _FlakyHttp:
    """Raises on the first ``fail_times`` get/post calls, then serves a real
    (terminal, parseable) response. Mirrors both call shapes this module uses:
    ``http.get(url, timeout=...)`` and ``http.post(url, data=..., headers=...,
    follow_redirects=..., timeout=...)``.
    """

    def __init__(self, fail_times: int, exc: Exception | None = None, ok_text: str = ""):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.ok_text = ok_text
        self.calls = 0

    async def _resolve(self) -> httpx.Response:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return httpx.Response(200, request=_REQ, text=self.ok_text)

    async def get(self, url, timeout=None):
        return await self._resolve()

    async def post(self, url, data=None, headers=None, follow_redirects=None, timeout=None):
        return await self._resolve()


class _BadStatusHttp:
    """Always returns a real, well-formed HTTP error response -- never raises a
    transport/timeout exception at all."""

    def __init__(self, status_code: int = 503, text: str = ""):
        self.status_code = status_code
        self.text = text
        self.calls = 0

    async def get(self, url, timeout=None):
        self.calls += 1
        return httpx.Response(self.status_code, request=_REQ, text=self.text)

    async def post(self, url, data=None, headers=None, follow_redirects=None, timeout=None):
        self.calls += 1
        return httpx.Response(self.status_code, request=_REQ, text=self.text)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(mod, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


# --- fetch_tax_sale: default-enabled path, single point of failure -----------------

def test_fetch_tax_sale_transient_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2, exc=httpx.ConnectTimeout("boom"), ok_text=_TAXSALE_HTML)
    parsed = asyncio.run(mod.fetch_tax_sale(http))
    assert http.calls == 3
    assert len(parsed.rows) == 1
    assert parsed.rows[0].pin == mod._normalize_parcel(_PIN)
    assert parsed.rows[0].amount == 500.0


def test_fetch_tax_sale_transient_timeout_that_never_clears_still_raises_not_hangs():
    http = _FlakyHttp(fail_times=99, exc=httpx.ConnectTimeout("boom"))
    with pytest.raises(httpx.ConnectTimeout):
        asyncio.run(mod.fetch_tax_sale(http))
    assert http.calls == 3   # stop_after_attempt(3), then gives up -- not an infinite hang


def test_fetch_tax_sale_real_http_error_status_is_not_retried():
    http = _BadStatusHttp(status_code=503)
    parsed = asyncio.run(mod.fetch_tax_sale(http))
    assert http.calls == 1   # a real bad status is not a transport/timeout error
    assert parsed == mod.TaxSaleParse(rows=[], unmapped=0)


# --- probate_search: gated, per-surname loop ----------------------------------------

def test_probate_search_transient_read_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2, exc=httpx.ReadTimeout("slow"), ok_text=_PROBATE_SEARCH_HTML)
    rows = asyncio.run(mod.probate_search(http, {}, "SMITH"))
    assert http.calls == 3
    assert rows == []


def test_probate_search_transient_timeout_that_never_clears_still_raises_not_hangs():
    http = _FlakyHttp(fail_times=99, exc=httpx.ReadTimeout("slow"))
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(mod.probate_search(http, {}, "SMITH"))
    assert http.calls == 3


def test_probate_search_real_http_error_status_is_not_retried():
    http = _BadStatusHttp(status_code=500)
    rows = asyncio.run(mod.probate_search(http, {}, "SMITH"))
    assert http.calls == 1
    assert rows == []


# --- collect_probate: gated, single point of failure for the whole probate pass ----

def test_collect_probate_transient_timeout_is_retried_and_then_succeeds():
    http = _FlakyHttp(fail_times=2, exc=httpx.ConnectTimeout("boom"), ok_text=_PROBATE_FORM_HTML)
    result = asyncio.run(mod.collect_probate(http, {}))
    assert http.calls == 3
    assert result == {}   # owners_by_surname is empty -> nothing further to fetch


def test_collect_probate_transient_timeout_that_never_clears_falls_back_not_hangs():
    http = _FlakyHttp(fail_times=99, exc=httpx.ConnectTimeout("boom"))
    result = asyncio.run(mod.collect_probate(http, {}))
    # stop_after_attempt(3) exhausts, reraise=True surfaces it, and the function's
    # OWN pre-existing try/except (unchanged by this fix) catches it and returns {}
    # rather than letting it propagate -- proving the retry budget is bounded, not
    # an infinite hang, while preserving the function's existing graceful fallback.
    assert http.calls == 3
    assert result == {}


def test_collect_probate_real_http_error_status_is_not_retried():
    http = _BadStatusHttp(status_code=503, text="")
    result = asyncio.run(mod.collect_probate(http, {}))
    assert http.calls == 1   # a real bad status is not a transport/timeout error
    assert result == {}
